from bugswarm.common.rest_api.database_api import DatabaseAPI
import os
import sys
from dotenv import load_dotenv
import re


def is_bugswarm_artifact_name(bugswarm_image: str) -> bool:
    pattern = r'^([a-zA-Z0-9]+-)+(\d+)$'
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
            trace = ''
            exception_trace_list = lines[i: i + 8]
            for j in range(len(exception_trace_list)):
                trace = trace + exception_trace_list[j] + '\n'
            exception_traces.append(trace)
    return exception_traces


def get_traceback_traces(log_text: str):
    lines = log_text.split('\n')
    exception_traces = []
    info = []
    for i, line in enumerate(lines):
        if lines[i].startswith('Traceback'):  # and lines[i + 1].startswith('\tFile'):
            trace = ''
            count = i
            while lines[count] != '':
                count = count + 1
            exception_trace_list = lines[i: count]
            trace_list_reverse = exception_trace_list[::-1]
            source_file_line = ''
            for w in trace_list_reverse:
                if w.startswith('  File'):
                    source_file_line = w
                    break
            match = re.match(r'  File "(.*)", line (.*), in (.*)',  source_file_line)
            info_ = {}
            info_['source_file'] = match.group(1)
            info_['line_no'] = match.group(2)
            info_['method_def'] = match.group(3)
            for j in range(len(exception_trace_list)):
                trace = trace + exception_trace_list[j] + '\n'
            info.append(info_)
            exception_traces.append(trace)
    return exception_traces, info

def get_python_traces(log_txt: str):
    lines = log_txt.splitlines()
    pattern_1 = r"^_+ ERROR .+\.py _+$"
    pattern_1_matching_lines = []
    for idx, line in enumerate(lines):
        if re.match(pattern_1, line.strip()):
            pattern_1_matching_lines.append(idx+1)


def get_test_failure_information(log_txt: str):
    test_failures = []
    pattern = re.compile(
        r'\s+([a-zA-Z0-9_$.]+)\.([a-zA-Z0-9_]+):(\d+) expected:<\[(.*?)\]> but was:<\[(.*?)\]>'
    )

    matches = pattern.findall(log_txt)
    for match in matches:
        test_failures.append(match)

    return test_failures

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

def make_sample_prompt(errors: str, exception: list, test_failures: list, info: list, container_txt:str):
    prompt = container_txt + 'Here is the bug from the container\n'
    if len(exception) > 0:
        prompt = prompt + 'We have found some exceptions/errors\n'
        for i in range(len(exception)):
            prompt = prompt + exception[i] + '\n'
    if errors != '':
        prompt = prompt + 'The error messages are given here\n' + errors
    if len(test_failures) > 0:
        prompt = prompt + 'List of test failures:\n'
        for t in test_failures:
            prompt = prompt + t
    return prompt

def get_problem_statement_from_failed_log(artifact_name: str):
    load_dotenv()
    token = os.getenv("BUGSWARM_TOKEN")
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
    test_failures = get_test_failure_information(log_txt=log_txt)
    return make_sample_prompt(errors, exception_list, test_failures, info, container_txt)

def write_problem_statement(statement, target_path):
    with open(target_path, "w") as file:
        file.write(statement)
        
if __name__ == "__main__":
    artifact = sys.argv[1]
    prb_stat = get_problem_statement_from_failed_log(artifact)
    target_path = f"Problem_statement/{artifact}.txt"
    write_problem_statement(prb_stat, target_path)