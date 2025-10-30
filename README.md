# CI-Bench

CI-Bench is a framework to evaluate LLM based tools on software engineering tasks on [BugSwarm](www.bugswarm.org) artifacts. 

## Supported Tasks and Tools

- [x] Automated Code Repair
  - [x] SWE-Agent
  - [x] Agentless
  - [x] Auto-code-rover
- [ ] Test Generation
- [ ] Fault Localization

We are working on adding more tasks and tools to the framework.

## Prerequisites
- Ubuntu 22.04
- Python 3.9 or above
- conda
- Docker
- bugswarm-client
- bugswarm-common
- [yq](https://github.com/mikefarah/yq?tab=readme-ov-file#install) (v4.46.1)

## General Usage

The following describes the steps to run CI-Bench on supported tasks and tools. For creating new tasks or benchmarking new tools, please refer to [this documentation](docs/creating-new-tasks.md).


### Set up the Tool

To set up the tool to be evaluated, run the following command.

```bash
bash setup.sh --task <task_name> --tool-name <tool> --virtual-env <env_option>
```

Required options:

- `task_name`: The targeted software engineering test. Can be `repair`, `testing`, or `localization`.
- `tool`: The tool to be evaluated. Can be `swe-agent`, `auto-code-rover`, or `agentless`.
- `env_option`: The virtual environment option. Can be `conda` or `python`.

Suppose we want to setup the `SWE-agent` tool on venv environment. So the command would be

```bash
bash setup.sh --task repair --tool-name swe-agent --virtual-env python
```


### Benchmarking the Tool

To benchmark the tool, run the following command.

```bash
bash run.sh --task <task_name> --tool-name <tool_name> --virtual-env <env_option> --artifact-id <bugswarm_artifact>
```

Lets consider we want to benchmark with an artifact `tananaev-traccar-64783123` on `SWE-agent` tool in python-venv environemnt.

The sample command will be

```bash
bash run.sh --task repair --tool-name swe-agent --virtual-env python --artifact-id tananaev-traccar-64783123
```

To run the benchmark with multiple artifacts, simply use a file with artifact IDs separated by new line.

```bash
bash run.sh --task <task_name> --tool-name <tool_name> --virtual-env <env_option> --artifact-list <file_path>
```

Required options:

- `task_type`: The targeted software engineering test. Can be `repair`, `testing`, or `localization`.
- `tool`: The tool to be evaluated. Can be `swe-agent`, `auto-code-rover`, or `agentless`.
- `env_option`: The virtual environment option. Can be `conda` or `python`.
- `bugswarm_artifact`: The [BugSwarm](https://www.bugswarm.org/dataset/) artifact ID for the benchmarking task.
- `file_path`: The file path containing the list of BugSwarm artifact IDs.

Lets consider we want to benchmark with an artifact `tananaev-traccar-64783123` on `SWE-agent` tool in python-venv environemnt
The sample command will be

```bash
bash run.sh --task repair --tool-name swe-agent --virtual-env python --artifact-id tananaev-traccar-64783123
```

The names of the artifacts are in the file named `artifacts.txt`, the command will be

```bash
bash run.sh --task repair --tool-name swe-agent --virtual-env python --artifact-list artifacts.txt
```

### Testing LLM based repair tool generated patch

Please remove the container and artifact image at first.

To test the LLM based repair tool generated patch, follow below:

```bash
export BUGSWARM_TOKEN="<token>"
```



Run the following command:

```bash
python3 components/executor.py <patch_file_path> <artifact-id>
```

Required options:

- `patch_file_path`: The path for the patch file
- `artifact-id`: The [BugSwarm](https://www.bugswarm.org/dataset/) artifact ID for the benchmarking task.


### Testing the LLM generated patch if they are SYE equivalent

You need to install `antlr4` at first

```bash
python -m pip install antlr4-python3-runtime==4.13.2
```

To know if the patch is syntactically equivalent:

```bash
bash evaluate.sh --tool_name <tool_name> --evaluation_metric SYE --bugswarm_artifact <artifact-id> --patch_file_path <patch_file_path>
```

Required options:

- `patch_file_path`: The path for the patch file
- `artifact-id`: The [BugSwarm](https://www.bugswarm.org/dataset/) artifact ID for the benchmarking task.
- `patch_file_path`: The path for the patch file

### Video Demonstration
The youtube video [link](https://www.youtube.com/watch?v=y8-OsPCvDwY) is here.

