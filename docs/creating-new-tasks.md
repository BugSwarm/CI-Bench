# Creating New Tasks and Benchmarking New Tools

This document describes the steps to create new tasks or benchmark new tools in CI-Bench.

### Building a YAML File

Here is an example of a yaml file

```bash
tool_name: SWE-Agent
parameters:
  config_file_path: config/default_from_url.yaml
  cost: 2.0
  model_name: gpt4o
  working_directory: swe-agent
  bugswarm_token: <token>
  openai_token: <token>
  anthropic_token: <token>
  venv_name: swe-agent

setup_commands:
  conda:
    - conda env create -f environment.yml
    - conda activate <venv_name>
    - echo 'OPENAI_API_KEY="<openai_token>"' > keys.cfg
    - echo 'ANTHROPIC_API_KEY="<anthropic_token>"' >> keys.cfg
    - echo 'BUGSWARM_TOKEN="<bugswarm_token>"' >> keys.cfg
    - ./setup.sh
  python:
    - python3 -m venv <venv_name>
    - source <venv_name>/bin/activate
    - python3 -m pip install --upgrade pip && pip install --editable .
    - echo 'OPENAI_API_KEY="<openai_token>"' > keys.cfg
    - echo 'ANTHROPIC_API_KEY="<anthropic_token>"' >> keys.cfg
    - echo 'BUGSWARM_TOKEN="<bugswarm_token>"' >> keys.cfg
    - ./setup.sh

run_commands:
  - python3 run.py --model_name <model_name> --config_file <config_file_path> --per_instance_cost_limit <cost> --bugswarm_image <bugswarm_artifact>
```

For parameters section, mention all the variables from the tool run command. Parameters keys should be as same as inside the command. Lets say, model_name is a parametre here. We have to keep the same `<model_name>` where we will use in the command. So we have to find out the variables from the command and put it in the parameters section. Parametre section also include the `working_directory` and `venv_name` as well. 

if you have `environment.yml` file, please keep the environment name same as yaml file. It is only for `conda` options where most of the time `environment.yml` file is present
 
And before running, please replace the necessary tokens inside the parameters

For `setup_commands`, we have two options. If anyone prefers to run on a conda environment, one should list all the virtual envionment related commands inside the `conda` sections. And if anyone wants to use `venv` command to create virtual
environment, one has to use the commands `python` sections.

Docker commands will be also included here. `run_commands` include necessary commands to run.