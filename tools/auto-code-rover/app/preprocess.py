import docker
import subprocess
from docker.errors import APIError
from bugswarm.common.rest_api.database_api import DatabaseAPI
import re
import logging
import os

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
    
def is_bugswarm_artifact_name(bugswarm_image: str) -> bool:
    pattern = pattern = r'^([a-zA-Z0-9]+-)+(\d+)$'
    match = re.match(pattern, bugswarm_image)
    if match:
        return True
    else:
        return False
    
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

def get_problem_statement_from_failed_log(artifact_name: str):
    token = "6OhVscXpfOtzmsPWFYLSsG_4kQgpV840wntraPgzph8"
    bugswarmapi = DatabaseAPI(token=token)
    response = bugswarmapi.find_artifact(artifact_name)
    response = response.json()
    errors = ''
    exception_list = []
    info = []
    
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


def get_project_from_image(artifact_name):
    if is_bugswarm_artifact_name(artifact_name):
        logging.debug(f"pulling {artifact_name} from bugswarm")
        client = docker.from_env()
        container_name = artifact_name
        try:
            # Check if a container with the same name already exists
            image_tag_full = 'bugswarm/cached-images:{}'.format(artifact_name)

            #if not is_docker_image_present(image_tag_full):
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
    container = client.containers.get(container_name)           
    command = f"docker cp {container.id}:/home/travis/build/failed/ /home/mnabil/auto-code-rover/projects/"

    subprocess.run(command, shell=True)
    
def issue_write(artifact_name, issue):
    os.makedirs("/home/mnabil/auto-code-rover/issue/" + artifact_name + ".txt", exist_ok=True)
    with open("/home/mnabil/auto-code-rover/issue/" + artifact_name, 'w') as f:
        f.write(issue)
        
    
get_project_from_image("bwhmather-verktyg-109227527")
issue = get_problem_statement_from_failed_log("bwhmather-verktyg-109227527")
issue_write("bwhmather-verktyg-109227527", issue)


