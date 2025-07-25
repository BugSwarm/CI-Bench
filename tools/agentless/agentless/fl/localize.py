import argparse
import concurrent.futures
import json
import os
import docker

from datasets import load_dataset
from tqdm import tqdm
import sys
import os
from bugswarm.common.rest_api.database_api import DatabaseAPI

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from agentless.fl.FL import LLMFL
from agentless.util.preprocess_data import (
    filter_none_python,
    filter_none_java,
    filter_out_test_files,
    get_full_file_paths_and_classes_and_functions,
    show_project_structure,
)
from agentless.util.utils import (
    load_existing_instance_ids,
    load_json,
    load_jsonl,
    setup_logger,
    get_problem_statement_from_failed_log
)
from get_repo_structure.get_repo_structure import (
    clone_repo,
    get_project_structure_from_scratch,
)

# SET THIS IF YOU WANT TO USE THE PREPROCESSED FILES
PROJECT_FILE_LOC = os.environ.get("PROJECT_FILE_LOC", None)


def localize_instance(
    bug, args, swe_bench_data, start_file_locs, existing_instance_ids
):
    bugswarm_image_id = args.bugswarm_image
    log_file = os.path.join(
        args.output_folder, "localization_logs", f"{bugswarm_image_id}.log"
    )

    logger = setup_logger(log_file)
    logger.info(f"Processing artifact {bugswarm_image_id}")

    token = os.getenv("BUGSWARM_TOKEN")
    bugswarmapi = DatabaseAPI(token=token)
    response = bugswarmapi.find_artifact(bugswarm_image_id)
    response = response.json()

    failed_commit_hash = response['failed_job']['trigger_sha']
    repo = response['repo'].split('/')[1]
    ci_service = response['ci_service']

    d = get_project_structure_from_scratch(
            repo, failed_commit_hash, bugswarm_image_id, "playground", ci_service
        )

    logger.info(f"================ localize {bugswarm_image_id} ================")

    problem_statement = get_problem_statement_from_failed_log(bugswarm_image_id, token)
    structure = d["structure"]

    if args.language == "python":
        filter_none_python(structure)  # some basic filtering steps
    else:
        filter_none_java(structure)

    found_files = []
    found_related_locs = []
    found_edit_locs = []
    additional_artifact_loc_file = None
    additional_artifact_loc_related = None
    additional_artifact_loc_edit_location = None
    file_traj, related_loc_traj, edit_loc_traj = {}, {}, {}

    # file level localization
    if args.file_level:
        fl = LLMFL(
            bugswarm_image_id,
            structure,
            problem_statement,
            args.model,
            args.backend,
            logger,
            args.match_partial_paths,
        )
        found_files, additional_artifact_loc_file, file_traj = fl.localize(
            mock=args.mock
        )
        logger.info("========Found Files========")
        logger.info(found_files)
    else:
        # assume start_file is provided
        for locs in start_file_locs:
            if locs["instance_id"] == d["instance_id"]:
                found_files = locs["found_files"]
                additional_artifact_loc_file = locs["additional_artifact_loc_file"]
                file_traj = locs["file_traj"]
                if "found_related_locs" in locs:
                    found_related_locs = locs["found_related_locs"]
                    additional_artifact_loc_related = locs[
                        "additional_artifact_loc_related"
                    ]
                    related_loc_traj = locs["related_loc_traj"]
                break

    # related class, functions, global var localization
    if args.related_level:
        if len(found_files) != 0:
            pred_files = found_files[: args.top_n]
            fl = LLMFL(
                d["instance_id"],
                structure,
                problem_statement,
                args.model,
                args.backend,
                logger,
                args.match_partial_paths,
            )
            additional_artifact_loc_related = []
            found_related_locs = []
            related_loc_traj = {}
            if args.compress:
                (
                    found_related_locs,
                    additional_artifact_loc_related,
                    related_loc_traj,
                ) = fl.localize_function_from_compressed_files(
                    pred_files, mock=args.mock
                )
                additional_artifact_loc_related = [additional_artifact_loc_related]
            else:
                assert False, "Not implemented yet."

    if args.fine_grain_line_level:
        # Only supports the following args for now
        pred_files = found_files[: args.top_n]
        fl = LLMFL(
            bugswarm_image_id,
            structure,
            problem_statement,
            args.model,
            args.backend,
            logger,
            args.match_partial_paths,
        )
        coarse_found_locs = {}
        for i, pred_file in enumerate(pred_files):
            if len(found_related_locs) > i:
                coarse_found_locs[pred_file] = found_related_locs[i]
        (
            found_edit_locs,
            additional_artifact_loc_edit_location,
            edit_loc_traj,
        ) = fl.localize_line_from_coarse_function_locs(
            pred_files,
            coarse_found_locs,
            context_window=args.context_window,
            language=args.language,
            add_space=args.add_space,
            no_line_number=args.no_line_number,
            sticky_scroll=args.sticky_scroll,
            mock=args.mock,
            temperature=args.temperature,
            num_samples=args.num_samples,
        )
        additional_artifact_loc_edit_location = [additional_artifact_loc_edit_location]

    with open(args.output_file, "a") as f:
        f.write(
            json.dumps(
                {
                    "instance_id": bugswarm_image_id,
                    "found_files": found_files,
                    "additional_artifact_loc_file": additional_artifact_loc_file,
                    "file_traj": file_traj,
                    "found_related_locs": found_related_locs,
                    "additional_artifact_loc_related": additional_artifact_loc_related,
                    "related_loc_traj": related_loc_traj,
                    "found_edit_locs": found_edit_locs,
                    "additional_artifact_loc_edit_location": additional_artifact_loc_edit_location,
                    "edit_loc_traj": edit_loc_traj,
                }
            )
            + "\n"
        )


def stop_and_remove_container(container_name):
    """
    Stops and removes a Docker container by its name.

    Args:
        container_name (str): Name of the Docker container to stop and remove.
    """
    # Initialize Docker client
    client = docker.from_env()

    try:
        # Get the container by name
        container = client.containers.get(container_name)

        # Stop the container if it's running
        if container.status == "running":
            print(f"Stopping container: {container_name}")
            container.stop()

        # Remove the container
        print(f"Removing container: {container_name}")
        container.remove()
        print(f"Container {container_name} stopped and removed successfully.")
    except docker.errors.NotFound:
        print(f"Container {container_name} not found.")
    except docker.errors.APIError as e:
        print(f"Error interacting with Docker API: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def localize(args):
    token = os.getenv("BUGSWARM_TOKEN")
    bugswarmapi = DatabaseAPI(token=token)
    response = bugswarmapi.find_artifact(args.bugswarm_image)
    response = response.json()

    if args.num_threads == 1:
        if args.bugswarm_image is not None:
            localize_instance(
                None, args, None, None, set()
            )
        else:
            swe_bench_data = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
            start_file_locs = load_jsonl(args.start_file) if args.start_file else None
            existing_instance_ids = (
                load_existing_instance_ids(args.output_file) if args.skip_existing else set()
            )
            for bug in swe_bench_data:
                localize_instance(
                    bug, args, swe_bench_data, start_file_locs, existing_instance_ids
                )
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.num_threads
        ) as executor:
            futures = [
                executor.submit(
                    localize_instance,
                    bug,
                    args,
                    swe_bench_data,
                    start_file_locs,
                    existing_instance_ids,
                )
                for bug in swe_bench_data
            ]
            concurrent.futures.wait(futures)
    stop_and_remove_container(args.bugswarm_image)


def merge(args):
    """Merge predicted locations."""
    start_file_locs = load_jsonl(args.start_file)

    # Dump each location sample.
    for st_id in range(args.num_samples):
        en_id = st_id
        merged_locs = []
        for locs in start_file_locs:
            merged_found_locs = []
            if "found_edit_locs" in locs and len(locs["found_edit_locs"]):
                merged_found_locs = [
                    "\n".join(x) for x in locs["found_edit_locs"][st_id]
                ]
            merged_locs.append({**locs, "found_edit_locs": merged_found_locs})
        with open(
            f"{args.output_folder}/loc_merged_{st_id}-{en_id}_outputs.jsonl", "w"
        ) as f:
            for data in merged_locs:
                f.write(json.dumps(data) + "\n")

    # Pair wise merge
    for st_id in range(0, args.num_samples - 1, 2):
        en_id = st_id + 1
        print(f"Merging sample {st_id} and {en_id}...")
        merged_locs = []
        for locs in start_file_locs:
            merged_found_locs = []
            if "found_edit_locs" in locs and len(locs["found_edit_locs"]):
                merged_found_locs = [
                    "\n".join(x) for x in locs["found_edit_locs"][st_id]
                ]
                for sample_found_locs in locs["found_edit_locs"][st_id + 1 : en_id + 1]:
                    for i, file_found_locs in enumerate(sample_found_locs):
                        if isinstance(file_found_locs, str):
                            merged_found_locs[i] += "\n" + file_found_locs
                        else:
                            merged_found_locs[i] += "\n" + "\n".join(file_found_locs)
            merged_locs.append({**locs, "found_edit_locs": merged_found_locs})
        with open(
            f"{args.output_folder}/loc_merged_{st_id}-{en_id}_outputs.jsonl", "w"
        ) as f:
            for data in merged_locs:
                f.write(json.dumps(data) + "\n")

    # ## Merge all
    all_merged_locs = []
    print("Merging all samples...")
    for locs in start_file_locs:
        merged_found_locs = []
        if "found_edit_locs" in locs and len(locs["found_edit_locs"]):
            merged_found_locs = ["\n".join(x) for x in locs["found_edit_locs"][0]]
            for sample_found_locs in locs["found_edit_locs"][1:]:
                for i, file_found_locs in enumerate(sample_found_locs):
                    if isinstance(file_found_locs, str):
                        merged_found_locs[i] += "\n" + file_found_locs
                    else:
                        merged_found_locs[i] += "\n" + "\n".join(file_found_locs)
        all_merged_locs.append({**locs, "found_edit_locs": merged_found_locs})
    with open(f"{args.output_folder}/loc_all_merged_outputs.jsonl", "w") as f:
        for data in all_merged_locs:
            f.write(json.dumps(data) + "\n")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--output_folder", type=str, required=True)
    parser.add_argument("--output_file", type=str, default="loc_outputs.jsonl")
    parser.add_argument(
        "--start_file",
        type=str,
        help="""previous output file to start with to reduce
        the work, should use in combination without --file_level""",
    )
    parser.add_argument("--file_level", action="store_true")
    parser.add_argument("--related_level", action="store_true")
    parser.add_argument("--fine_grain_line_level", action="store_true")
    parser.add_argument("--top_n", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--num_samples", type=int, default=1)
    parser.add_argument("--compress", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--add_space", action="store_true")
    parser.add_argument("--no_line_number", action="store_true")
    parser.add_argument("--sticky_scroll", action="store_true")
    parser.add_argument(
        "--match_partial_paths",
        action="store_true",
        help="Whether to match model generated files based on subdirectories of original repository if no full matches can be found",
    )
    parser.add_argument("--context_window", type=int, default=10)
    parser.add_argument(
        "--num_threads",
        type=int,
        default=1,
        help="Number of threads to use for creating API requests",
    )
    parser.add_argument("--target_id", type=str)
    parser.add_argument(
        "--skip_existing",
        action="store_true",
        help="Skip localization of instance id's which already contain a localization in the output file.",
    )
    parser.add_argument(
        "--mock", action="store_true", help="Mock run to compute prompt tokens."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-2024-05-13",
        choices=["gpt-4o-2024-05-13", "deepseek-coder", "gpt-4o-mini-2024-07-18", "claude-3-5-sonnet-20241022", "gemini-2.5-pro", "gemini-2.5-flash", "Qwen3-235B-A22B-fp8-tput", "DeepSeek-V3", "DeepSeek-R1-Distill-Llama-70B"],
    )
    parser.add_argument(
        "--backend", type=str, default="openai", choices=["openai", "deepseek", "anthropic", "google", "meta-llama", "deepseek-ai", "Qwen"]
    )
    
    parser.add_argument(
        "--bugswarm_image",
        type=str,
        help="The name of the bugswarm artifact which we want to analyze",
        required=True
    )

    parser.add_argument(
        "--language",
        choices=["java", "python"],
        type=str,
        help="The language of the bugswarm artifact which we want to analyze",
        required=True
    )

    args = parser.parse_args()

    import os

    args.output_file = os.path.join(args.output_folder, args.output_file)

    assert (
        not os.path.exists(args.output_file) or args.skip_existing
    ), "Output file already exists and not set to skip existing localizations"

    assert not (
        args.file_level and args.start_file
    ), "Cannot use both file_level and start_file"

    assert not (
        args.file_level and args.fine_grain_line_level and not args.related_level
    ), "Cannot use both file_level and fine_grain_line_level without related_level"

    assert not (
        (not args.file_level) and (not args.start_file)
    ), "Must use either file_level or start_file"

    assert (not "deepseek" in args.model) or (
        args.backend == "deepseek"
    ), "Must specify `--backend deepseek` if using a DeepSeek model"

    os.makedirs(os.path.join(args.output_folder, "localization_logs"), exist_ok=True)
    os.makedirs(args.output_folder, exist_ok=True)

    # write the arguments
    with open(f"{args.output_folder}/args.json", "w") as f:
        json.dump(vars(args), f, indent=4)

    if args.merge:
        merge(args)
    else:
        localize(args)


if __name__ == "__main__":
    main()
