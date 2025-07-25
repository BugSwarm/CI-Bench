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
- Python 3.9
- Docker
- [yq](https://github.com/mikefarah/yq?tab=readme-ov-file#install)

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


### Benchmarking the Tool

To benchmark the tool, run the following command.

```bash
bash run.sh --task <task_name> --tool-name <tool_name> --virtual-env <env_option> --artifact-id <bugswarm_artifact>
```

To run the benchmark with multiple artifacts, simply use a file with artifact IDs separated by new line.

```bash
bash run.sh --task <task_name> --tool-name <tool_name> --virtual-env <env_option> --artifact-list <file_path>
```

Required options:

- `task_type`: The targeted software engineering test. Can be `repair`, `testing`, or `localization`.
- `tool`: The tool to be evaluated. Can be `swe-agent`, `auto-code-rover`, or `agentless`.
- `env_option`: The virtual environment option. Can be `conda` or `venv`.
- `bugswarm_artifact`: The [BugSwarm](https://www.bugswarm.org/dataset/) artifact ID for the benchmarking task.
- `file_path`: The file path containing the list of BugSwarm artifact IDs.

### Testing LLM based repair tool generated patch

To test the LLM based repair tool generated patch, run the following command:

```bash
python3 components/executor.py <patch_file_path> <artifact-id>
```

Required oprions:

- `patch_file_path`: The path for the patch file
- `artifact-id`: The [BugSwarm](https://www.bugswarm.org/dataset/) artifact ID for the benchmarking task.



