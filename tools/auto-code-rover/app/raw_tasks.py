import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from os.path import join as pjoin
from pathlib import Path
import docker
import subprocess
from docker.errors import APIError
from bugswarm.common.rest_api.database_api import DatabaseAPI

import httpx

from app import utils as app_utils
from app.log import log_and_print
from app.task import PlainTask, SweTask, Task


class RawTask(ABC):
    @property
    @abstractmethod
    def task_id(self) -> str:
        raise NotImplementedError("abstract base class")
  
    @property  
    @abstractmethod
    def language(self) -> str:
        raise NotImplementedError("abstract base class")

    @abstractmethod
    def to_task(self) -> Task:
        raise NotImplementedError("abstract base class")

    @abstractmethod
    def dump_meta_data(self, output_dir: str) -> None:
        raise NotImplementedError("abstract base class")


class RawSweTask(RawTask):
    """
    Encapsulate everything required to run one task.
    """

    def __init__(self, task_id: str, setup_info: dict, task_info: dict):
        # a counter str, format "1/150", which means first task out of 150
        # id from the benchmark
        self._task_id = task_id
        # setup_info (Dict): keys: ['repo_path', 'env_name', 'pre_install', 'install','test_cmd']
        self.setup_info = setup_info
        # task_info (Dict): keys: ['base_commit', 'hints_text', 'created_at',
        # 'test_patch', 'repo', 'problem_statement', 'version', 'instance_id',
        # 'FAIL_TO_PASS', 'PASS_TO_PASS', 'environment_setup_commit']
        self.task_info = task_info
        self._language = 'python'

    @property
    def task_id(self) -> str:
        return self._task_id
    
    @property
    def language(self) -> str:
        return self._language

    def to_task(self) -> SweTask:
        task_id = self.task_id
        setup_info = self.setup_info
        task_info = self.task_info
        return SweTask(
            task_id=task_id,
            problem_statement=task_info["problem_statement"],
            repo_path=setup_info["repo_path"],
            env_name=setup_info["env_name"],
            pre_install_cmds=setup_info["pre_install"],
            install_cmd=setup_info["install"],
            # command to run the relevant tests,
            test_cmd=setup_info["test_cmd"],
            commit=task_info["base_commit"],
            repo_name=task_info["repo"],
            # modifications to the test suite for this task instance,
            test_patch=task_info["test_patch"],
            testcases_passing=task_info["PASS_TO_PASS"],
            testcases_failing=task_info["FAIL_TO_PASS"],
        )

    def dump_meta_data(self, output_dir: str):
        meta = {
            "task_id": self.task_id,
            "setup_info": self.setup_info,
            "task_info": self.task_info,
            "language": "python"
        }
        with open(pjoin(output_dir, "meta.json"), "w") as f:
            json.dump(meta, f, indent=4)
        with open(pjoin(output_dir, "problem_statement.txt"), "w") as f:
            f.write(self.task_info["problem_statement"])
        with open(pjoin(output_dir, "developer_patch.diff"), "w") as f:
            f.write(self.task_info["patch"])


class RawBugswarmTask(RawTask):
    def __init__(
        self,
        task_id: str,
        setup_dir: str,
    ):
        self._task_id = task_id
        self.bugswarm_image_id = task_id
        self.setup_dir = setup_dir
        if not os.path.exists(self.setup_dir):
            os.makedirs(self.setup_dir)
        self.clone_path = pjoin(self.setup_dir, self.task_id)
        self.token = os.getenv("BUGSWARM_TOKEN")
        bugswarmapi = DatabaseAPI(token=self.token)
        response = bugswarmapi.find_artifact(self.task_id)
        response = response.json()
        self.commit_hash = response['failed_job']['trigger_sha']
        self._language = response['lang'].lower()
        self.ci_service = response["ci_service"]
        self.get_project_from_image()
        self.problem_statement = self.get_problem_statement_from_failed_log()
        print(self.problem_statement)

    @property
    def task_id(self) -> str:
        return self._task_id
    
    @property
    def language(self) -> str:
        return self._language

    # def image_pull(self):
    def get_failed_log(self):
        bugswarmapi = DatabaseAPI(token=self.token)
        a = bugswarmapi.get_build_log(self.task_id.split('-')[-1])

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

    def get_errors_from_logs(self, log_txt):
        errors = ''
        count = 0
        lines = log_txt.split('\n')
        for line in lines:
            if line.startswith("[ERROR]") or line.startswith("E"):
                count = count + 1
                errors = errors + line + '\n'
        return str(errors)

    def get_errors_from_logs_python(self, log_txt: str):
        errors = ''
        count = 0
        lines = log_txt.split('\n')
        for line in lines:
            if 'error' in line.lower():
                count = count + 1
                errors = errors + line + '\n'
        return str(errors)

    def get_exception_informations(self, log_txt: str):
        lines = log_txt.split('\n')
        exception_traces = []
        for i, line in enumerate(lines):
            if ('exception' in lines[i].lower() or 'error' in lines[i].lower()) and lines[i + 1].startswith('\tat') and not lines[i].startswith('\tat'):
                # print(line)
                trace = ''
                exception_trace_list = lines[i: i + 8]
                for j in range(len(exception_trace_list)):
                    trace = trace + exception_trace_list[j] + '\n'
                # print(exception_trace_list)
                exception_traces.append(trace)
        return exception_traces

    def get_traceback_traces(self, log_text: str):
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

    def get_test_failure_information(self, log_txt: str):
        test_failures = []
        pattern = re.compile(
            r'\s+([a-zA-Z0-9_$.]+)\.([a-zA-Z0-9_]+):(\d+) expected:<\[(.*?)\]> but was:<\[(.*?)\]>'
        )

        matches = pattern.findall(log_txt)
        for match in matches:
            test_failures.append(match)

        return test_failures

    def make_sample_prompt(self, errors: str, exception: list, test_failures: list, info: list, container_txt:str):
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

    def get_problem_statement_from_failed_log(self):
        errors = ''
        exception_list = []
        info = []

        container_txt = 'We are now working on the bugswarm container "' + self.task_id + '".'
        container_txt = container_txt + 'The ci service is ' + self.ci_service + '. It is a ' + self.language + ' artifact.'
        log_txt = self.get_failed_log()
        if self.language.lower() == 'java':
            errors = self.get_errors_from_logs(log_txt=log_txt)
            exception_list = self.get_exception_informations(log_txt=log_txt)
        elif self.language.lower() == 'python':
            exception_list, info = self.get_traceback_traces(log_text=log_txt)
            errors = self.get_errors_from_logs_python(log_txt=log_txt)
        test_failures = self.get_test_failure_information(log_txt=log_txt)
        return self.make_sample_prompt(errors, exception_list, test_failures, info, container_txt)

    def dump_meta_data(self, output_dir: str):
        meta = {
            "task_info": {
                "base_commit": self.commit_hash,
                "problem_statement": self.problem_statement,
                "instance_id": self.task_id,
                "language": self.language
            }, 
            "setup_info": {"repo_path": self.clone_path},
        }

        meta_file = pjoin(output_dir, "meta.json")

        with open(meta_file, "w") as f:
            json.dump(meta, f, indent=4)
            
    def extract_folder_and_file(self, target_path: str):
        try:
            # Initialize Docker client
            client = docker.from_env()

            # Get the container instance
            container = client.containers.get(self.task_id)

            # Run a shell command in the container to list the directory contents
            command = f"ls {target_path}"
            target_output = container.exec_run(command).output.decode('utf-8').strip()

            # Extract the folder at the target path
            folder_list = target_output.splitlines()  # Assumes there's only one folder
            extra = ["requirements.zip", "requirements", "cacher", "cacher.zip"]
            for x in extra:
                if x in folder_list:
                    folder_list.remove(x)
            folder_name = folder_list[0]
            folder_path = f"{target_path}/{folder_name}"

            # List contents of the subdirectory
            command = f"ls {folder_path}"
            folder_output = container.exec_run(command).output.decode('utf-8').strip()

            # Filter and collect required items ("requirements.zip" is optional)
            items = folder_output.splitlines()
            print("items ",items)
            return folder_name, items[0]

        except docker.errors.NotFound:
            return f"Container '{self.task_id}' not found."
        except docker.errors.APIError as e:
            return f"Docker API error: {e}"
        except Exception as e:
            return f"An error occurred: {e}"

    def get_project_from_image(self):
        client = docker.from_env()
        container_name = self.task_id
        try:
            # Check if a container with the same name already exists
            image_tag_full = 'bugswarm/cached-images:{}'.format(self.task_id)

            # if not is_docker_image_present(image_tag_full):
            client.images.pull(image_tag_full)

            # if not is_container_running(image_tag_full):
            client.containers.run(image_tag_full, detach=True, name=container_name, command='tail -f /dev/null')
            # container.restart()
            #  print(f"Container started with ID: {container.id}")
        except APIError as e:
            if "409" in str(e):
                print(f"Conflict error: {e.explanation}")
                # Handle the conflict error as needed
            else:
                print(f"API error occurred: {e.explanation}")
                # Rename the container
                # container.rename(self.env.bugswarm_image)
        container = client.containers.get(container_name)
        target_path = f"/home/{self.ci_service}/build/failed/"
        f1, f2 = self.extract_folder_and_file(target_path)
        target_path_ = f"/home/{self.ci_service}/build/failed/{f1}/{f2}/"
        com = f"docker cp {container.id}:{target_path_} {self.clone_path}"

        subprocess.run(com, shell=True)
        
    def to_task(self) -> PlainTask:
        return PlainTask(
            commit_hash=self.commit_hash,
            local_path=self.clone_path,
            problem_statement=self.problem_statement,
            language=self.language
        )


class RawGithubTask(RawTask):
    def __init__(
        self,
        task_id: str,
        clone_link: str,
        commit_hash: str | None,
        issue_link: str,
        setup_dir: str,
        use_comments: bool = False,
    ):
        self._task_id = task_id
        self.clone_link = clone_link
        # if commit_hash is None, assume using the HEAD of default branch
        self.commit_hash = commit_hash
        self.issue_link = issue_link
        self.setup_dir = setup_dir
        self.use_comments = use_comments
        self.clone_path = pjoin(self.setup_dir, self.task_id)
        self._language = 'python'
        self.problem_statement, self.created_at = self.fetch_issue()
        self.clone_repo()

    @property
    def task_id(self) -> str:
        return self._task_id
    
    @property
    def language(self) -> str:
        return self._language

    def clone_repo(self):
        clone_path = Path(self.clone_path)
        if os.path.exists(clone_path):
            log_and_print(
                f"Path {clone_path} already exists. Removing it to get a fresh clone."
            )
            shutil.rmtree(clone_path)
        app_utils.clone_repo(self.clone_link, str(clone_path.parent), clone_path.name)
        log_and_print(f"Cloned source code to {clone_path}.")
        if self.commit_hash is None:
            # let's get the current commit hash
            with app_utils.cd(clone_path):
                self.commit_hash = app_utils.get_current_commit_hash()

    def dump_meta_data(self, output_dir: str):
        meta = {
            "task_info": {
                "base_commit": self.commit_hash,
                "created_at": self.created_at,
                "problem_statement": self.problem_statement,
                "instance_id": self.task_id,
                "language": self.language
            },
            "setup_info": {"repo_path": self.clone_path},
        }

        meta_file = pjoin(output_dir, "meta.json")

        with open(meta_file, "w") as f:
            json.dump(meta, f, indent=4)

    def fetch_issue(self):
        if "github.com" not in self.issue_link:
            raise NotImplementedError("Only GitHub issues are supported for now.")

        retrieved_issue = self.fetch_github_issue(self.issue_link, self.use_comments)

        if retrieved_issue is None:
            raise RuntimeError(
                f"Failed to retrieve issue information from {self.issue_link}"
            )

        title, body, created_at = retrieved_issue

        body = self.process_links(body)

        problem_statement = f"{title}\n{body}"

        return problem_statement, created_at

    @classmethod
    def process_links(cls, body: str):
        code_pattern = re.compile(
            r"https://github.com/(.*?)/blob/(.*)/(.*)#L(\d+)-L(\d+)"
        )
        replacements = []

        for code_links in code_pattern.finditer(body):
            repo_name = code_links.group(1)
            commit = code_links.group(2)
            file_path = code_links.group(3)
            start_line = int(code_links.group(4))
            end_line = int(code_links.group(5))

            file_contents = httpx.get(
                f"https://raw.githubusercontent.com/{repo_name}/{commit}/{file_path}"
            ).text.splitlines()
            fragment = "\n".join(file_contents[start_line - 1 : end_line])

            replacements.append((code_links.group(0), f"\n```{fragment }```\n"))

        for code_link, replacement in replacements:
            body = body.replace(code_link, code_link + replacement)
        return body

    @classmethod
    def fetch_github_issue(
        cls, issue_url: str, use_comments: bool = False
    ) -> tuple[str, str, str]:
        """Extract owner, repo, and issue number from the URL"""

        # Example issue URL: https://github.com/owner/repo/issues/123

        _, owner, repo, _, issue_number = issue_url.rsplit("/", 4)

        api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        comments_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"

        issue_response = httpx.get(api_url)

        if issue_response.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch issue information: {issue_response.status_code}"
            )

        issue_info = issue_response.json()

        title = issue_info["title"]
        body = issue_info["body"]

        if use_comments:
            comments_response = httpx.get(comments_url)
            if comments_response.status_code != 200:
                raise RuntimeError(
                    f"Failed to fetch comments information: {comments_response.status_code}"
                )

            comments_info = comments_response.json()
            for comment in comments_info:
                if (
                    "user" not in comment
                    or comment["user"]["type"] == "Bot"
                    or comment["user"]["login"] == "acr-bot"
                ):
                    continue

                body += (
                    f"\nUser: {comment['user']['login']}\nComment: {comment['body']}"
                )

        created_at = issue_info["created_at"]

        return title, body, created_at

    def to_task(self) -> PlainTask:
        return PlainTask(
            commit_hash=self.commit_hash,
            local_path=self.clone_path,
            problem_statement=self.problem_statement,
            language='python'
        )


class RawLocalTask(RawTask):
    """
    Encapsulate everything required to run ACR on a local issue on the disk.
    """

    def __init__(self, task_id: str, local_repo: str, issue_file: str):
        self._task_id = task_id
        self.local_repo = local_repo
        self.issue_file = issue_file
        self.commit_hash = self.init_local_repo()
        self.problem_statement = self.read_issue_from_file()

    @property
    def task_id(self) -> str:
        return self._task_id

    def init_local_repo(self):
        with app_utils.cd(self.local_repo):
            if not app_utils.is_git_repo():
                # non git repo - let's make it a git repo first
                app_utils.initialize_git_repo_and_commit()
            commit = app_utils.get_current_commit_hash()
        return commit

    def read_issue_from_file(self) -> str:
        # ignore encoding errors so at least we can have some issue content
        issue = Path(self.issue_file).read_text(errors="ignore")
        return issue

    def dump_meta_data(self, output_dir: str):
        meta = {
            "task_info": {
                "base_commit": self.commit_hash,
                "problem_statement": self.problem_statement,
                "instance_id": self.task_id,
                "language": "python"
            },
            "setup_info": {"repo_path": self.local_repo},
        }

        meta_file = pjoin(output_dir, "meta.json")

        with open(meta_file, "w") as f:
            json.dump(meta, f, indent=4)

    def to_task(self) -> PlainTask:
        return PlainTask(
            commit_hash=self.commit_hash,
            local_path=self.local_repo,
            problem_statement=self.problem_statement,
            language='python'
        )
