from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
import traceback
from io import BytesIO
from pathlib import Path
from subprocess import PIPE, STDOUT
from typing import Any, Callable
import logging

from datasets import load_dataset, load_from_disk
from ghapi.all import GhApi
from git import InvalidGitRepositoryError, Repo
from bugswarm.common.rest_api.database_api import DatabaseAPI

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from sweagent.utils.config import keys_config
from sweagent.utils.log import get_logger

DOCKER_START_UP_DELAY = float(keys_config.get("SWE_AGENT_DOCKER_START_UP_DELAY", 1))
GITHUB_ISSUE_URL_PATTERN = re.compile(r"github\.com\/(.*?)\/(.*?)\/issues\/(\d+)")
GITHUB_REPO_URL_PATTERN = re.compile(r".*[/@]?github\.com\/([^/]+)\/([^/]+)")

logger = get_logger("env_utils")


def get_data_path_name(bugswarm_image: str) -> str:
    """if bugswarm_image is a file, return the file stem
    elif it's a github url, return the owner__repo_name
    """
    if bugswarm_image.startswith("text://"):
        return hashlib.sha256(bugswarm_image.removeprefix("text://").encode()).hexdigest()[:6]
    match = GITHUB_ISSUE_URL_PATTERN.search(bugswarm_image)
    if match:
        owner, repo, _ = match.groups()
        return f"{owner}__{repo}"
    return Path(bugswarm_image).stem


def is_github_issue_url(bugswarm_image: str) -> bool:
    """Check if bugswarm_image is an URL pointing to a github issue"""
    return GITHUB_ISSUE_URL_PATTERN.search(bugswarm_image) is not None


def is_github_repo_url(bugswarm_image: str) -> bool:
    """Check if bugswarm_image is an URL pointing to a github repository.
    Paths to issues or PRs will also match this pattern.
    """
    return GITHUB_REPO_URL_PATTERN.search(bugswarm_image) is not None

def is_bugswarm_artifact_name(bugswarm_image: str) -> bool:
    pattern = pattern = r'^([a-zA-Z0-9]+-)+(\d+)$'
    match = re.match(pattern, bugswarm_image)
    if match:
        return True
    else:
        return False

# TODO: Why not just use copy_anything_to_container?
def copy_file_to_container(container: Container, contents: str, container_path: str) -> None:
    """
    Copies a given string into a Docker container at a specified path.

    Args:
        container: Docker SDK container object.
        contents: The string to copy into the container.
        container_path: The path inside the container where the string should be copied to.

    Returns:
        None
    """
    temp_file_name = None

    try:
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file_name = temp_file.name
            # Write the string to the temporary file and ensure it's written to disk
            temp_file.write(contents.encode("utf-8"))
            temp_file.flush()
            os.fsync(temp_file.fileno())

        # Create a TAR archive in memory containing the temporary file
        with tempfile.NamedTemporaryFile():
            with open(temp_file_name, "rb") as temp_file:
                # Prepare the TAR archive
                with BytesIO() as tar_stream:
                    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                        tar_info = tarfile.TarInfo(name=os.path.basename(container_path))
                        tar_info.size = os.path.getsize(temp_file_name)
                        tar.addfile(tarinfo=tar_info, fileobj=temp_file)
                    tar_stream.seek(0)
                    # Copy the TAR stream to the container
                    container.put_archive(path=os.path.dirname(container_path), data=tar_stream.read())

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        logger.error(traceback.format_exc())
    finally:
        # Cleanup: Remove the temporary file if it was created
        if temp_file_name and os.path.exists(temp_file_name):
            os.remove(temp_file_name)


def copy_anything_to_container(container: Container, host_path: str, container_path: str) -> None:
    """Copy files or directories from host to container

    Note: Will need to set ownership on the copied files in the container.
    """
    if not Path(host_path).exists():
        msg = f"Path {host_path} does not exist, cannot copy it to container."
        raise FileNotFoundError(msg)
    cmd = ["docker", "cp", host_path, f"{container.id}:{container_path}"]
    logger.debug(f"Copying {host_path} to container at {container_path} with command: {shlex.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        msg = f"Error copying {host_path} to container at {container_path}: {e}"
        raise RuntimeError(msg) from e


def read_with_timeout(container: subprocess.Popen, pid_func: Callable, timeout_duration: int | float) -> str:
    """
    Read data from a subprocess with a timeout.
    This function uses a file descriptor to read data from the subprocess in a non-blocking way.

    Args:
        container: The subprocess container.
        pid_func: A function that returns a list of process IDs (except the PID of the main process).
        timeout_duration: The timeout duration in seconds.

    Returns:
        output: The data read from the subprocess, stripped of trailing newline characters.

    Raises:
        TimeoutError: If the timeout duration is reached while reading from the subprocess.
    """
    buffer = b""
    fd = container.stdout.fileno()
    end_time = time.time() + timeout_duration

    # Select is not available on windows
    is_windows = platform.system() == "Windows"
    if not is_windows:
        import select
    else:
        os.set_blocking(fd, False)

    def ready_to_read(fd) -> bool:
        if is_windows:
            # We can't do the extra check
            return True
        return bool(select.select([fd], [], [], 0.01)[0])

    while time.time() < end_time:
        pids = pid_func()
        if len(pids) > 0:
            # There are still PIDs running
            time.sleep(0.05)
            continue
        if ready_to_read(fd):
            data = os.read(fd, 4096)
            if data:
                buffer += data
        else:
            # No more data to read
            break
        time.sleep(0.05)  # Prevents CPU hogging

    if container.poll() is not None:
        msg = f"Subprocess exited unexpectedly.\nCurrent buffer: {buffer.decode()}"
        raise RuntimeError(msg)
    if time.time() >= end_time:
        msg = f"Timeout reached while reading from subprocess.\nCurrent buffer: {buffer.decode()}\nRunning PIDs: {pids}"
        raise TimeoutError(msg)
    return buffer.decode()


PROCESS_DONE_MARKER_START = "///PROCESS-DONE:"
PROCESS_DONE_MARKER_END = ":PROCESS-DONE///"
PROCESS_DONE_REGEX = re.compile(rf"{PROCESS_DONE_MARKER_START}(.+?){PROCESS_DONE_MARKER_END}")


def read_with_timeout_experimental(container: subprocess.Popen, timeout_duration: int | float) -> tuple[str, str]:
    """
    Read data from a subprocess with a timeout.
    This function uses a file descriptor to read data from the subprocess in a non-blocking way.

    NOTE: This is an experimental implementation that is faster than `read_with_timeout`, but
    has not been thoroughly tested.

    Args:
        container: The subprocess container.
        timeout_duration: The timeout duration in seconds.

    Returns:
        Output and exit code, both as strings (!)

    Raises:
        TimeoutError: If the timeout duration is reached while reading from the subprocess.
    """
    buffer = b""
    fd = container.stdout.fileno()
    end_time = time.time() + timeout_duration

    # Select is not available on windows
    is_windows = platform.system() == "Windows"
    if not is_windows:
        import select
    else:
        os.set_blocking(fd, False)

    def ready_to_read(fd) -> bool:
        if is_windows:
            # We can't do the extra check
            return True
        return bool(select.select([fd], [], [], 0.01)[0])

    n_decode_failures = 0
    while time.time() < end_time:
        if ready_to_read(fd):
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                logger.error("BlockingIOError while reading from subprocess.", exc_info=True)
                break
            if data:
                buffer += data
                try:
                    decoded = buffer.decode()
                except UnicodeDecodeError:
                    n_decode_failures += 1
                    if n_decode_failures > 30:
                        msg = "Too many decode failures while reading from subprocess."
                        raise RuntimeError(msg)
                if PROCESS_DONE_MARKER_START in decoded:
                    break
        time.sleep(0.01)  # Prevents CPU hogging

    if container.poll() is not None:
        msg = f"Subprocess exited unexpectedly.\nCurrent buffer: {buffer.decode()}"
        raise RuntimeError(msg)
    if time.time() >= end_time:
        msg = f"Timeout reached while reading from subprocess.\nCurrent buffer: {buffer.decode()}"
        raise TimeoutError(msg)
    decoded = buffer.decode()
    body = "\n".join(line for line in decoded.splitlines() if not line.startswith(PROCESS_DONE_MARKER_START))
    _results = PROCESS_DONE_REGEX.search(decoded)
    if _results is None:
        msg = f"Could not find process done marker in last line: {decoded=}, {body=}"
        raise ValueError(msg)
    exit_code = _results.group(1)
    return body, exit_code


def get_background_pids(container_obj: Container):
    pids = container_obj.exec_run("ps -eo pid,comm --no-headers").output.decode().split("\n")
    pids = [x.split() for x in pids if x]
    pids = [x for x in pids if x[1] not in {"ps"} and x[0] != "1"]
    bash_pids = [x for x in pids if x[1] == "bash"]
    other_pids = [x for x in pids if x[1] not in {"bash"}]
    return bash_pids, other_pids


def _get_non_persistent_container(ctr_name: str, image_name: str) -> tuple[subprocess.Popen, set[str]]:
    startup_cmd = [
        "docker",
        "run",
        "-i",
        "--rm",
        "--name",
        ctr_name,
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        image_name,
        "/bin/bash",
        "-l",
    ]
    logger.debug("Starting container with command: %s", shlex.join(startup_cmd))
    container = subprocess.Popen(
        startup_cmd,
        stdin=PIPE,
        stdout=PIPE,
        stderr=STDOUT,
        text=True,
        bufsize=1,  # line buffered
    )
    time.sleep(DOCKER_START_UP_DELAY)
    # try to read output from container setup (usually an error), timeout if no output
    output = read_with_timeout(container, lambda: list(), timeout_duration=10)
    if output:
        logger.error(f"Unexpected container setup output: {output}")
    # bash PID is always 1 for non-persistent containers
    return container, {
        "1",
    }


def _get_persistent_container(
    ctr_name: str, image_name: str, persistent: bool = False
) -> tuple[subprocess.Popen, set[str]]:
    client = docker.from_env()
    containers = client.containers.list(all=True, filters={"name": ctr_name})
    if ctr_name in [c.name for c in containers]:
        container_obj = client.containers.get(ctr_name)
        if container_obj.status in {"created"}:
            container_obj.start()
        elif container_obj.status in {"running"}:
            pass
        elif container_obj.status in {"exited"}:
            container_obj.restart()
        elif container_obj.status in {"paused"}:
            container_obj.unpause()
        else:
            msg = f"Unexpected container status: {container_obj.status}"
            raise RuntimeError(msg)
    else:
        container_obj = client.containers.run(
            image_name,
            command="/bin/bash -l -m",
            name=ctr_name,
            stdin_open=True,
            tty=True,
            detach=True,
            auto_remove=not persistent,
        )
        container_obj.start()
    startup_cmd = [
        "docker",
        "exec",
        "-i",
        ctr_name,
        "/bin/bash",
        "-l",
    ]
    logger.debug("Starting container with command: %s", shlex.join(startup_cmd))
    container = subprocess.Popen(
        startup_cmd,
        stdin=PIPE,
        stdout=PIPE,
        stderr=STDOUT,
        text=True,
        bufsize=1,  # line buffered
    )
    time.sleep(DOCKER_START_UP_DELAY)
    # try to read output from container setup (usually an error), timeout if no output
    output = read_with_timeout(container, lambda: list(), timeout_duration=2)
    if output:
        logger.error(f"Unexpected container setup output: {output}")
    # Get the process IDs of the container
    # There should be at least a head process and possibly one child bash process
    bash_pids, other_pids = get_background_pids(container_obj)
    total_time_slept = DOCKER_START_UP_DELAY
    # Let's wait for a maximum of 5 x DOCKER_START_UP_DELAY seconds
    # and then check again.
    while len(bash_pids) > 1 or len(other_pids) > 0:
        time.sleep(1)
        total_time_slept += 1
        bash_pids, other_pids = get_background_pids(container_obj)
        if total_time_slept > 5 * DOCKER_START_UP_DELAY:
            break
    bash_pid = 1
    if len(bash_pids) == 1:
        bash_pid = bash_pids[0][0]
    elif len(bash_pids) > 1 or len(other_pids) > 0:
        msg = (
            "Detected alien processes attached or running. Please ensure that no other agents "
            f"are running on this container. PIDs: {bash_pids}, {other_pids}"
        )
        raise RuntimeError(msg)
    return container, {str(bash_pid), "1"}


def get_container(ctr_name: str, image_name: str, persistent: bool = False) -> tuple[subprocess.Popen, set]:
    """
    Get a container object for a given container name and image name

    Arguments:
        ctr_name (str): Name of container
        image_name (str): Name of image
        persistent (bool): Whether to use a persistent container or not
    Returns:
        Container object
    """
    if not image_exists(image_name):
        msg = (
            f"Image {image_name} not found. Please ensure it is built and available. "
            "Please double-check that you followed all installation/setup instructions from the "
            "readme."
        )
        raise RuntimeError(msg)

    if persistent:
        return _get_persistent_container(ctr_name, image_name)
    else:
        return _get_non_persistent_container(ctr_name, image_name)


def image_exists(image_name: str) -> bool:
    """
    Check that the image exists and give some better error messages.

    Arguments:
        image_name: Name of image
    Returns:
        bool: True if image exists
    """
    try:
        client = docker.from_env()
    except docker.errors.DockerException as e:
        docker_not_running = any(
            (
                "connection aborted" in str(e).lower(),
                "connection refused" in str(e).lower(),
                "error while fetching server api version" in str(e).lower(),
            ),
        )
        if docker_not_running:
            msg = (
                "Probably the Docker daemon is not running. Please start the Docker daemon and try again. "
                "You might need to allow the use of the docker socket "
                "(https://github.com/princeton-nlp/SWE-agent/issues/159) or symlink the socket "
                "if it's at a non-standard location "
                "(https://github.com/princeton-nlp/SWE-agent/issues/20#issuecomment-2047506005)."
            )
            raise RuntimeError(msg) from e
        raise
    filterred_images = client.images.list(filters={"reference": image_name})
    if len(filterred_images) == 0:
        return False
    elif len(filterred_images) > 1:
        RuntimeError(f"Multiple images found for {image_name}, that's weird.")
    attrs = filterred_images[0].attrs
    if attrs is not None:
        logger.info(
            f"Found image {image_name} with tags: {attrs['RepoTags']}, created: {attrs['Created']} "
            f"for {attrs['Os']} {attrs['Architecture']}.",
        )
    return True


def is_container_running(container_name:str) -> bool:
    # Connect to the Docker daemon
    client = docker.from_env()
    
    try:
        # Get the container object by name or ID
        container = client.containers.get(container_name)
        
        # Check if the container is running
        if container.status == 'running':
            print(f"Container '{container_name}' is running.")
            return True
        else:
            print(f"Container '{container_name}' is not running. Status: {container.status}")
            return False
    except docker.errors.NotFound:
        print(f"Container '{container_name}' not found.")
        return False
    except docker.errors.APIError as e:
        print(f"Error connecting to Docker: {e}")
        return False


def get_commit(api: GhApi, owner: str, repo: str, ref: str | None = None):
    """Get commit object from github api

    Args:
        api (GhApi):
        owner (str): Repo owner, e.g., "princeton-nlp"
        repo (str): Repo, e.g., "SWE-agent"
        ref (str, optional): Branch, tag or commit hash

    Returns:
        _type_: _description_
    """
    if ref:
        return api.repos.get_commit(owner, repo, ref)
    return api.repos.list_commits(owner, repo)[0]


class InvalidGithubURL(ValueError): ...


def parse_gh_issue_url(issue_url: str) -> tuple[str, str, str]:
    """
    Returns:
        owner: Repo owner
        repo: Repo name
        issue number: Issue number as str

    Raises:
        InvalidGithubURL: If the URL is not a valid github issue URL
    """
    match = GITHUB_ISSUE_URL_PATTERN.search(issue_url)
    if not match:
        msg = f"Invalid GitHub issue URL: {issue_url}"
        raise InvalidGithubURL(msg)
    res = match.groups()
    assert len(res) == 3
    return tuple(res)  # type: ignore


def parse_gh_repo_url(repo_url: str) -> tuple[str, str]:
    """
    Returns:
        owner: Repo owner/org
        repo: Repo name

    Raises:
        InvalidGithubURL: If the URL is not a valid github repo URL
    """
    match = GITHUB_REPO_URL_PATTERN.search(repo_url)
    if not match:
        msg = f"Invalid GitHub issue URL: {repo_url}"
        raise InvalidGithubURL(msg)
    res = match.groups()
    assert len(res) == 2
    return tuple(res)  # type: ignore


def get_gh_issue_data(issue_url: str, *, token: str = ""):
    """Returns github issue data in the form of a dictionary.
    See https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28#get-an-issue
    for return format
    """
    owner, repo, issue_number = parse_gh_issue_url(issue_url)
    api = GhApi(token=token)
    return api.issues.get(owner, repo, issue_number)


def get_problem_statement_from_github_issue(owner: str, repo: str, issue_number: str, *, token: str | None = "") -> str:
    """Return problem statement from github issue"""
    api = GhApi(token=token)
    issue = api.issues.get(owner, repo, issue_number)
    title = issue.title if issue.title else ""
    body = issue.body if issue.body else ""
    return f"{title}\n{body}\n"

def get_failed_log(image_tag: str, token: str | None = None):
    bugswarmapi = DatabaseAPI(token=token)
    a = bugswarmapi.get_build_log(image_tag.split('-')[-1])

    ansi_escape = re.compile(r'''
        \x1B  # ESC
        \[    # [
        [0-?]*  # 0 or more characters from 0 to ?
        [ -/]*  # 0 or more characters from space to /
        [@-~]   # 1 character from @ to ~
    ''', re.VERBOSE)

    # Remove ANSI escape codes
    cleaned_log_output = ansi_escape.sub('', a)
    
    timestamp_pattern = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ')

    # Replace the timestamps with an empty string
    modified_log = timestamp_pattern.sub('', cleaned_log_output)
        
    return modified_log

def get_errors_from_logs(log_txt: str):
    errors = ''
    count = 0
    lines = log_txt.split('\n')
    for line in lines:
        if line.startswith("[ERROR]") or line.startswith("E"):
            count = count + 1
            errors = errors + line + '\n'
    return str(errors)

def get_errors_from_logs_python(log_txt: str):
    errors = ''
    count = 0
    lines = log_txt.split('\n')
    for line in lines:
        if 'error' in line.lower():
            count = count + 1
            errors = errors + line + '\n'
    return str(errors)

def get_exception_informations(log_txt: str):
    lines = log_txt.split('\n')
    exception_traces = []
    for i, line in enumerate(lines):
        if ('exception' in lines[i].lower() or 'error' in lines[i].lower()) and lines[i + 1].startswith('\tat') and not lines[i].startswith('\tat'):
            #print(line)
            trace = ''
            exception_trace_list = lines[i: i + 8]
            for j in range(len(exception_trace_list)):
                trace = trace + exception_trace_list[j] + '\n'
            #print(exception_trace_list)
            exception_traces.append(trace)
    return exception_traces

def get_traceback_traces(log_text: str):
    lines = log_text.split('\n')
    exception_traces = []
    info = []
    for i, line in enumerate(lines):
        if lines[i].startswith('Traceback'): # and lines[i + 1].startswith('\tFile'):
            trace = ''
            count = i
            while lines[count] != '':
                count = count + 1
            exception_trace_list = lines[i: count]
            trace_list_reverse = exception_trace_list[::-1]
            # print(trace_list_reverse)
            source_file_line = ''
            for w in trace_list_reverse:
                if w.startswith('  File'):
                    source_file_line = w
                    # print(source_file_line)
                    break
            match = re.match(r'  File "(.*)", line (.*), in (.*)',  source_file_line)
            info_ = {}
            info_['source_file'] = match.group(1)
            info_['line_no'] = match.group(2)
            info_['method_def'] = match.group(3)
            for j in range(len(exception_trace_list)):
                trace = trace + exception_trace_list[j] + '\n'
            #print(exception_trace_list)
            info.append(info_)
            exception_traces.append(trace)
    return exception_traces, info

def get_test_failure_information(log_txt: str):
    test_failures = []
    pattern = re.compile(
        r'\s+([a-zA-Z0-9_$.]+)\.([a-zA-Z0-9_]+):(\d+) expected:<\[(.*?)\]> but was:<\[(.*?)\]>'
    )
    
    matches = pattern.findall(log_txt)
    for match in matches:
        test_failures.append(match)
        
    return test_failures

def make_sample_prompt(errors: str, exception: list, test_failures: list, info: list, container_txt:str):
    prompt = container_txt + 'Here is the bug from the container\n'
    if len(exception) > 0:
        prompt = prompt + 'We have found some exceptions/errors\n'
        for i in range(len(exception)):
            # prompt = prompt + 'The errors occurred at ' + info[i]['source_file'] + ', line no ' + info[i]['line_no'] + ' and method name ' + info[i]['method_def']
            prompt = prompt + exception[i] + '\n'
    if errors != '':
        prompt = prompt + 'The error messages are given here\n' + errors
    if len(test_failures) > 0:
        prompt = prompt + 'List of test failures:\n'
        for t in test_failures:
            prompt = prompt + t
    return prompt

def is_container_running(image_name):
    try:
        # Run the docker ps command to check for running containers with the given image name
        result = subprocess.run(
            ['docker', 'ps', '-q', '--filter', f'ancestor={image_name}'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        
        # Return True if any container ID is found, False otherwise
        return bool(result.stdout.strip())
    
    except subprocess.CalledProcessError as e:
        print(f"Error checking for running Docker container: {e}")
        return False

def stop_and_remove_container(container_id):
    try:
        # Stop the container
        subprocess.run(['docker', 'stop', container_id], check=True)
        # Remove the container
        subprocess.run(['docker', 'rm', container_id], check=True)
        print(f"Stopped and removed container with ID: {container_id}")
    
    except subprocess.CalledProcessError as e:
        print(f"Error stopping/removing Docker container: {e}")


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
                           
            
def get_problem_statement_from_failed_log(artifact_name: str, token: str | None = None):
    bugswarmapi = DatabaseAPI(token=token)
    response = bugswarmapi.find_artifact(artifact_name)
    response = response.json()
    errors = ''
    exception_list = []
    info = []
    if is_bugswarm_artifact_name(artifact_name):
        logging.debug(f"pulling {artifact_name} from bugswarm")
        client = docker.from_env()
        container_name = artifact_name
        try:
            # Check if a container with the same name already exists
            image_tag_full = 'bugswarm/cached-images:{}'.format(artifact_name)

            if not is_docker_image_present(image_tag_full):
                client.images.pull(image_tag_full)
            
            #if not is_container_running(image_tag_full):
            client.containers.run(image_tag_full, detach=True, name=container_name, command='tail -f /dev/null')
            # container.restart()
            #  print(f"Container started with ID: {container.id}")
        except APIError as e:
            if "409" in str(e):
                logging.error(f"Conflict error: {e.explanation}")
                # Handle the conflict error as needed
            else:
                logging.error(f"API error occurred: {e.explanation}")
                # Rename the container
                # container.rename(self.env.bugswarm_image)
    
    # container = client.containers.get(artifact_name)
    # container_id = container.id
    container_txt = 'We are now working on the bugswarm container "' + artifact_name + '".'
    container_txt = container_txt + 'The ci service is ' + response["ci_service"] + '. It is a ' + response["lang"] + ' artifact.'
    log_txt = get_failed_log(artifact_name, token)
    if response['lang'].lower() == 'java':
        errors = get_errors_from_logs(log_txt=log_txt)
        exception_list = get_exception_informations(log_txt=log_txt)
    elif response['lang'].lower() == 'python':
        # container_txt = container_txt + ''
        exception_list, info = get_traceback_traces(log_text=log_txt)
        errors = get_errors_from_logs_python(log_txt=log_txt)
    # logger.info(get_errors_from_logs)
    # logger.info(exception_list)
    test_failures = get_test_failure_information(log_txt=log_txt)
    # logger.info(test_failures)
    return make_sample_prompt(errors, exception_list, test_failures, info, container_txt)
    

class InstanceBuilder:
    def __init__(self, token: str | None = None, b_token: str | None = None):
        """This helper class is used to build the data for an instance object,
        retrieving problem statements from github issues or local files and setting
        repo paths from github urls or local paths.
        """
        # Args that will be passed to the Instance constructor
        self.args = {}
        self.token = token
        self.b_token = b_token
        self._instance_id_problem_suffix = ""

    def set_problem_statement_from_gh_issue(self, issue_url: str):
        owner, repo, issue_number = parse_gh_issue_url(issue_url)
        self.args["problem_statement"] = get_problem_statement_from_github_issue(
            owner,
            repo,
            issue_number,
            token=self.token,
        )
        self.args["instance_id"] = f"{owner}__{repo}-i{issue_number}"
        self.args["problem_statement_source"] = "online"

    def set_problem_statement_from_file(self, file_path: str):
        self.set_problem_statement_from_text(Path(file_path).read_text())

    def set_problem_statement_from_text(self, text: str):
        self.args["problem_statement"] = text
        self.args["instance_id"] = hashlib.sha256(self.args["problem_statement"].encode()).hexdigest()[:6]
        self.args["problem_statement_source"] = "local"
        
    def set_problem_statement_from_failed_log(self, artifact_name: str):
        prompt = get_problem_statement_from_failed_log(artifact_name, self.b_token)
        self.args["problem_statement"] = prompt
        self.args["instance_id"] = hashlib.sha256(self.args["problem_statement"].encode()).hexdigest()[:6]
        self.args["problem_statement_source"] = "bugswarm"

    def set_problem_statement(self, bugswarm_image: str):
        """Get problem statement for a single instance from a github issue url or a
        path to a markdown or text file.
        """
        if bugswarm_image.startswith("text://"):
            return self.set_problem_statement_from_text(bugswarm_image.removeprefix("text://"))
        if is_github_issue_url(bugswarm_image):
            return self.set_problem_statement_from_gh_issue(bugswarm_image)
        if Path(bugswarm_image).is_file():
            return self.set_problem_statement_from_file(bugswarm_image)
        if is_bugswarm_artifact_name(bugswarm_image):
            return self.set_problem_statement_from_failed_log(bugswarm_image)
        msg = f"Not sure how to get problem statement from {bugswarm_image=}."
        raise ValueError(msg)

    def set_repo_info_from_gh_url(self, url: str, base_commit: str | None = None):
        owner, repo = parse_gh_repo_url(url)
        self.args["repo"] = f"{owner}/{repo}"
        self.args["repo_type"] = "github"
        # Always get commit hash, because base_commit can also be branch or tag
        api = GhApi(token=self.token)
        self.args["base_commit"] = get_commit(api, owner, repo, ref=base_commit).sha
        if base_commit != self.args["base_commit"]:
            logger.info(f"Base commit reference {base_commit} resolved to commit hash {self.args['base_commit']}")
        self.args["version"] = self.args["base_commit"][:7]

    def set_repo_info_from_local_path(self, path: str, base_commit: str | None = None):
        self.args["repo"] = str(Path(path).resolve())
        self.args["repo_type"] = "local"
        if base_commit:
            self.args["base_commit"] = base_commit
        else:
            try:
                repo = Repo(path, search_parent_directories=True)
            except InvalidGitRepositoryError as e:
                msg = f"Could not find git repository at {path=}."
                raise ValueError(msg) from e
            if repo.is_dirty():
                msg = f"Local git repository {path} is dirty. Please commit or stash changes."
                raise ValueError(msg)
            self.args["base_commit"] = repo.head.object.hexsha
        self.args["version"] = self.args["base_commit"][:7]
        
    def set_repo_info_for_bugswarm_artifact(self, artifact_name:str):
        bugswarmapi = DatabaseAPI(token=self.b_token)
        response = bugswarmapi.find_artifact(artifact_name)
        if not response.ok:
            return
        
        artifact = response.json()
        self.args["base_commit"] = artifact['failed_job']['trigger_sha']
        # user = artifact['repo'].split('/')[0]
        self.args["repo"] = artifact['repo']
        self.args["repo_type"] = "github"
        self.args["version"] = self.args["base_commit"][:7]
        self.args["ci_service"] = artifact['ci_service']
        

    def set_repo_info(self, repo: str, base_commit: str | None = None):
        if is_github_repo_url(repo):
            self.set_repo_info_from_gh_url(repo, base_commit=base_commit)
        elif Path(repo).is_dir():
            self.set_repo_info_from_local_path(repo, base_commit=base_commit)
        else:
            msg = f"Could not determine repo path from {repo=}."
            raise ValueError(msg)

    def set_from_dict(self, instance_dict: dict[str, Any]):
        self.args |= instance_dict

    def set_missing_fields(self):
        # TODO: This field is only needed while swe_env is using some questionable logic
        # to determine whether to clone from a mirror or not. This should be removed in the future.
        # Values: 'swe-bench' (loaded from json/jsonl for swe-bench style inference),
        # 'online' (loaded from github issue or similar) or 'local' (loaded from local file)
        if "problem_statement_source" not in self.args:
            self.args["problem_statement_source"] = "swe-bench"
        if "repo_type" not in self.args:
            self.args["repo_type"] = "github"

    def validate(self):
        required_fields = [
            "problem_statement",
            "instance_id",
            "repo",
            "repo_type",
            "base_commit",
            "version",
            "problem_statement_source",
        ]
        if not all(x in self.args for x in required_fields):
            missing = set(required_fields) - set(self.args.keys())
            msg = f"Missing required fields: {missing=}"
            raise ValueError(msg)
        if self.args["repo_type"] not in {"github", "local"}:
            msg = f"Invalid repo type: {self.args['repo_type']=}"
            raise ValueError(msg)
        if self.args["repo_type"] == "github" and self.args["repo"].count("/") != 1:
            msg = f"Invalid repo format for {self.args['repo_type']=}: {self.args['repo']=}"
            raise ValueError(msg)

    def build(self) -> dict[str, Any]:
        self.set_missing_fields()
        self.validate()
        return self.args


def get_instances(
    file_path: str,
    base_commit: str | None = None,
    split: str | None = None,
    token: str | None = None,
    *,
    repo_path: str = "",
    b_token: str | None = None
) -> list[dict[str, Any]]:
    """
    Getter function for handling json, jsonl files

    Args:
        file_path (str): Path to file

    Returns:
        List of instances as dictionaries
    """

    def instance_from_dict(instances):
        ib = InstanceBuilder(token=token, b_token=b_token)
        ib.set_from_dict(instances)
        return ib.build()

    def postproc_instance_list(instances):
        if isinstance(instances, dict):
            msg = "Expected a list of instances, got a dictionary."
            raise ValueError(msg)
        return [instance_from_dict(x) for x in instances]

    # The next if statement is very brittle logic to determine if we're processing a single instance
    if (
        file_path.startswith("text://")
        or (Path(file_path).is_file() and Path(file_path).suffix in [".md", ".txt"])
        or is_github_issue_url(file_path)
        or is_bugswarm_artifact_name(file_path)
    ):
        ib = InstanceBuilder(token=token, b_token=b_token)
        ib.set_problem_statement(file_path)
        if repo_path:
            ib.set_repo_info(repo_path, base_commit=base_commit)
        elif is_github_repo_url(file_path):
            ib.set_repo_info_from_gh_url(file_path, base_commit=base_commit)
        elif is_bugswarm_artifact_name(file_path):
            ib.set_repo_info_for_bugswarm_artifact(file_path)
        else:
            msg = f"Could not determine repo path from {file_path=}, {repo_path=}"
            raise ValueError(msg)

        return [ib.build()]

    if base_commit:
        msg = "base_commit must be empty if running over multiple problem statements"
        raise ValueError(msg)

    if repo_path:
        msg = "repo_path must be empty if running over multiple problem statements"
        raise ValueError(msg)

    # If file_path is a directory, attempt load from disk
    if os.path.isdir(file_path):
        try:
            dataset_or_dict = load_from_disk(file_path)
            if isinstance(dataset_or_dict, dict):
                return postproc_instance_list(dataset_or_dict[split])
            return postproc_instance_list(dataset_or_dict)
        except FileNotFoundError:
            # Raised by load_from_disk if the directory is not a dataset directory
            pass

    # The next if statement is very brittle logic to determine if we're processing a single instance
    if (
        (Path(file_path).is_file() and Path(file_path).suffix in [".md", ".txt"])
        or is_github_issue_url(file_path)
        or file_path.startswith("text://")
        or is_bugswarm_artifact_name(file_path)
    ):
        ib = InstanceBuilder(token=token, b_token=b_token)
        ib.set_problem_statement(file_path)
        if repo_path:
            ib.set_repo_info(repo_path, base_commit=base_commit)
        elif is_github_repo_url(file_path):
            ib.set_repo_info_from_gh_url(file_path)
        elif is_bugswarm_artifact_name(file_path):
            logger.info(f"bugswarm artifact")
            ib.set_repo_info_for_bugswarm_artifact(file_path)
        else:
            msg = f"Could not determine repo path from {file_path=}, {repo_path=}"
            raise ValueError(msg)

        return [ib.build()]

    if base_commit is not None:
        msg = "base_commit must be None if bugswarm_image is not a github issue url"
        raise ValueError(msg)

    # If file_path is a file, load the file
    if file_path.endswith(".json"):
        with open(file_path) as file:
            return postproc_instance_list(json.load(file))
    if file_path.endswith(".jsonl"):
        return postproc_instance_list([json.loads(x) for x in Path(file_path).read_text().splitlines(keepends=True)])

    # Attempt load from HF datasets as a last resort
    logger.info(is_bugswarm_artifact_name(file_path))
    if not is_bugswarm_artifact_name(file_path):
        try:
            return postproc_instance_list(load_dataset(file_path, split=split))
        except Exception as e:
            msg = (
                f"Could not load instances from {file_path}. "
                "Please ensure --bugswarm_image is a GitHub URL, a SWE-bench HuggingFace dataset, or a JSON/JSONL file."
            )
            raise ValueError(msg) from e


def get_associated_commit_urls(org: str, repo: str, issue_number: str, *, token: str = "") -> list[str]:
    """Return the URLs of commits that would close an issue."""
    api = GhApi(token=token)
    # Strangely the "pull_request" field of api.issues.get is often not set
    # so we have to go through the events to check if there's a commit
    events = api.issues.list_events(org, repo, issue_number)
    commit_urls = []
    for event in events:
        if event.event != "referenced":
            continue
        if not event.commit_id:
            continue
        commit = api.repos.get_commit(org, repo, event.commit_id)
        message = commit.commit.message
        if f"fixes #{issue_number}" in message.lower() or f"closes #{issue_number}" in message.lower():
            commit_urls.append(commit.html_url)
    return commit_urls


def remove_triple_backticks(text: str) -> str:
    return "\n".join(line.removeprefix("```") for line in text.splitlines())


def format_trajectory_markdown(trajectory: list[dict[str, str]]):
    """Format a trajectory as a markdown string for use in gh PR description."""
    prefix = [
        "<details>",
        "<summary>Thought process ('trajectory') of SWE-agent (click to expand)</summary>",
        "",
        "",
    ]
    steps = []
    for i, step in enumerate(trajectory):
        step_strs = [
            f"**🧑‍🚒 Response ({i})**: ",
            f"{step['response'].strip()}",
            f"**👀‍ Observation ({i})**:",
            "```",
            f"{remove_triple_backticks(step['observation']).strip()}",
            "```",
        ]
        steps.append("\n".join(step_strs))
    suffix = [
        "",
        "</details>",
    ]
    return "\n".join(prefix) + "\n\n---\n\n".join(steps) + "\n".join(suffix)
