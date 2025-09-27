import ast
import os
import subprocess
import uuid
import logging

import docker
from docker.errors import APIError
import re

repo_to_top_folder = {
    "django/django": "django",
    "sphinx-doc/sphinx": "sphinx",
    "scikit-learn/scikit-learn": "scikit-learn",
    "sympy/sympy": "sympy",
    "pytest-dev/pytest": "pytest",
    "matplotlib/matplotlib": "matplotlib",
    "astropy/astropy": "astropy",
    "pydata/xarray": "xarray",
    "mwaskom/seaborn": "seaborn",
    "psf/requests": "requests",
    "pylint-dev/pylint": "pylint",
    "pallets/flask": "flask",
}


def checkout_commit(repo_path, commit_id):
    """Checkout the specified commit in the given local git repository.
    :param repo_path: Path to the local git repository
    :param commit_id: Commit ID to checkout
    :return: None
    """
    try:
        # Change directory to the provided repository path and checkout the specified commit
        print(f"Checking out commit {commit_id} in repository at {repo_path}...")
        subprocess.run(["git", "-C", repo_path, "checkout", commit_id], check=True)
        print("Commit checked out successfully.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running git command: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def clone_repo(repo_name, repo_playground):
    try:
        print(
            f"Cloning repository from https://github.com/{repo_name}.git to {repo_playground}/{repo_to_top_folder[repo_name]}..."
        )
        subprocess.run(
            [
                "git",
                "clone",
                f"https://github.com/{repo_name}.git",
                f"{repo_playground}/{repo_to_top_folder[repo_name]}",
            ],
            check=True,
        )
        print("Repository cloned successfully.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running git command: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


def is_docker_image_present(image_name):
    try:
        # Run the docker images command and capture the output
        result = subprocess.run(
            ['docker', 'images', '-q', f'{image_name}'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        # If the output is non-empty, the image exists
        if result.stdout.strip():
            return True
        else:
            return False

    except subprocess.CalledProcessError as e:
        print(f"Error checking for Docker image: {e}")
        return False


def is_bugswarm_artifact_name(bugswarm_image: str) -> bool:
    pattern = r'^[a-zA-Z0-9_\-]+-(\d+)'
    match = re.match(pattern, bugswarm_image)
    if match:
        return True
    else:
        return False


def get_project_from_image(artifact_name, repo_playground, ci_service):
    if is_bugswarm_artifact_name(artifact_name):
        logging.debug(f"pulling {artifact_name} from bugswarm")
        client = docker.from_env()
        container_name = artifact_name
        try:
            # Check if a container with the same name already exists
            image_tag_full = 'bugswarm/cached-images:{}'.format(artifact_name)

            # if not is_docker_image_present(image_tag_full):
            client.images.pull(image_tag_full)

            # if not is_container_running(image_tag_full):
            client.containers.run(image_tag_full, detach=True, name=container_name, command='tail -f /dev/null')
        except APIError as e:
            if "409" in str(e):
                logging.error(f"Conflict error: {e.explanation}")
                # Handle the conflict error as needed
            else:
                logging.error(f"API error occurred: {e.explanation}")
                # Rename the container
                # container.rename(self.env.bugswarm_image)
    container = client.containers.get(container_name)
    command = f"cd {repo_playground} && docker cp {container.id}:/home/{ci_service}/build/failed/ ."

    subprocess.run(command, shell=True)


def get_names_in_path(container_name, target_path):
    client = docker.from_env()

    try:
        # Get the container
        container = client.containers.get(container_name)

        # Execute ls command to list files in the target path
        cmd = f"ls {target_path}"
        result = container.exec_run(cmd)

        # Decode the result and filter out b.zip
        items = result.output.decode('utf-8').strip().split('\n')
        filtered_items = [item for item in items if item != "b.zip"]

        return tuple(filtered_items)

    except docker.errors.NotFound:
        raise ValueError(f"Container {container_name} not found.")
    except Exception as e:
        raise RuntimeError(f"An error occurred: {e}")


def extract_folder_and_file(container_name: str, target_path: str):
    try:
        # Initialize Docker client
        client = docker.from_env()

        # Get the container instance
        container = client.containers.get(container_name)

        # Run a shell command in the container to list the directory contents
        command = f"ls {target_path}"
        target_output = container.exec_run(command).output.decode('utf-8').strip()

        # Extract the folder at the target path
        folder_name = target_output.splitlines()[0]  # Assumes there's only one folder
        folder_path = f"{target_path}/{folder_name}"

        # List contents of the subdirectory
        command = f"ls {folder_path}"
        folder_output = container.exec_run(command).output.decode('utf-8').strip()

        # Filter and collect required items ("requirements.zip" is optional)
        items = folder_output.splitlines()
        if "requirements.zip" in items:
            items.remove("requirements.zip")

        return folder_name, items[0]

    except docker.errors.NotFound:
        return f"Container '{container_name}' not found."
    except docker.errors.APIError as e:
        return f"Docker API error: {e}"
    except Exception as e:
        return f"An error occurred: {e}"


def get_project_structure_from_scratch(
    repo_name, commit_id, instance_id, repo_playground, ci_service
):

    # Generate a temperary folder and add uuid to avoid collision
    repo_playground = os.path.join(repo_playground, str(uuid.uuid4()))

    # assert playground doesn't exist
    assert not os.path.exists(repo_playground), f"{repo_playground} already exists"

    # create playground
    os.makedirs(repo_playground)
    if is_bugswarm_artifact_name(instance_id):
        get_project_from_image(instance_id, repo_playground, ci_service)
    else:
        clone_repo(repo_name, repo_playground)
    # checkout_commit(f"{repo_playground}/{repo_to_top_folder[repo_name]}", commit_id)
    f1, f2 = extract_folder_and_file(instance_id, f'/home/{ci_service}/build/failed')
    cmd = f"cd {repo_playground}/failed/{f1}/{f2}/ && git clean -fdx"
    subprocess.run(cmd, shell=True)
    structure = create_structure(f"{repo_playground}/failed/{f1}/{f2}/")
    # clean up

    d = {
        "repo": f"{f1}/{f2}",
        "base_commit": commit_id,
        "structure": structure,
        "instance_id": instance_id,
    }
    return d


def parse_python_file(file_path, file_content=None):
    """Parse a Python file to extract class and function definitions with their line numbers.
    :param file_path: Path to the Python file.
    :return: Class names, function names, and file contents
    """
    if file_content is None:
        try:
            with open(file_path, "r") as file:
                file_content = file.read()
                parsed_data = ast.parse(file_content)
        except Exception as e:  # Catch all types of exceptions
            print(f"Error in file {file_path}: {e}")
            return [], [], ""
    else:
        try:
            parsed_data = ast.parse(file_content)
        except Exception as e:  # Catch all types of exceptions
            print(f"Error in file {file_path}: {e}")
            return [], [], ""

    class_info = []
    function_names = []
    class_methods = set()

    for node in ast.walk(parsed_data):
        if isinstance(node, ast.ClassDef):
            methods = []
            for n in node.body:
                if isinstance(n, ast.FunctionDef):
                    methods.append(
                        {
                            "name": n.name,
                            "start_line": n.lineno,
                            "end_line": n.end_lineno,
                            "text": file_content.splitlines()[
                                n.lineno - 1: n.end_lineno
                            ],
                        }
                    )
                    class_methods.add(n.name)
            class_info.append(
                {
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                    "text": file_content.splitlines()[
                        node.lineno - 1: node.end_lineno
                    ],
                    "methods": methods,
                }
            )
        elif isinstance(node, ast.FunctionDef) and not isinstance(
            node, ast.AsyncFunctionDef
        ):
            if node.name not in class_methods:
                function_names.append(
                    {
                        "name": node.name,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "text": file_content.splitlines()[
                            node.lineno - 1: node.end_lineno
                        ],
                    }
                )

    return class_info, function_names, file_content.splitlines()


def parse_java_file(file_path, file_content=None):
    """
    Parse a Java file to extract class and method definitions with their line numbers.
    :param file_path: Path to the Java file.
    :param file_content: Optional file content string. If provided, file_path is ignored.
    :return: Class information, method information, and file content as a list of lines.
    """
    if file_content is None:
        try:
            with open(file_path, "r") as file:
                file_content = file.readlines()
        except Exception as e:  # Catch all types of exceptions
            print(f"Error in file {file_path}: {e}")
            return [], [], []

    class_info = []
    method_info = []
    lines = file_content if isinstance(file_content, list) else file_content.splitlines()

    # Regular expressions for class and method definitions
    class_pattern = r'^\s*(public|protected|private)?\s*(abstract|final)?\s*class\s+(\w+)\s*'
    method_pattern = r'^\s*(public|protected|private|static|final|abstract|synchronized)?\s*([\w<>\[\]]+\s+)?(\w+)\s*\(([^)]*)\)\s*{?'

    current_class = None
    class_start_line = None

    for i, line in enumerate(lines, start=1):
        # Match class definition
        class_match = re.match(class_pattern, line)
        if class_match:
            if current_class:  # Save the previous class if we're entering a new one
                class_info.append({
                    "name": current_class,
                    "start_line": class_start_line,
                    "end_line": i - 1,
                    "text": lines[class_start_line - 1:i - 1]
                })
            current_class = class_match.group(3)
            class_start_line = i
            continue

        # Match method definition
        method_match = re.match(method_pattern, line)
        if method_match:
            method_name = method_match.group(3)
            method_info.append({
                "name": method_name,
                "start_line": i,
                "text": [line]
            })

    # Add the last class if any
    if current_class:
        class_info.append({
            "name": current_class,
            "start_line": class_start_line,
            "end_line": len(lines),
            "text": lines[class_start_line - 1:]
        })

    return class_info, method_info, lines


def create_structure(directory_path):
    """Create the structure of the repository directory by parsing Python files.
    :param directory_path: Path to the repository directory.
    :return: A dictionary representing the structure.
    """
    structure = {}
    for root, _, files in os.walk(directory_path):
        repo_name = os.path.basename(directory_path)
        relative_root = os.path.relpath(root, directory_path)
        if relative_root == ".":
            relative_root = repo_name
        curr_struct = structure
        for part in relative_root.split(os.sep):
            if part not in curr_struct:
                curr_struct[part] = {}
            curr_struct = curr_struct[part]
        for file_name in files:
            if file_name.endswith(".py"):
                file_path = os.path.join(root, file_name)
                class_info, function_names, file_lines = parse_python_file(file_path)
                curr_struct[file_name] = {
                    "classes": class_info,
                    "functions": function_names,
                    "text": file_lines,
                }
            elif file_name.endswith(".java"):
                file_path = os.path.join(root, file_name)
                class_info, function_names, file_lines = parse_java_file(file_path)
                curr_struct[file_name] = {
                    "classes": class_info,
                    "functions": function_names,
                    "text": file_lines,
                }
            else:
                curr_struct[file_name] = {}

    return structure
