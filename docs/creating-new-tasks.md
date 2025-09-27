# Creating New Tasks and Benchmarking New Tools

This document describes the steps to create new tasks or benchmark new tools in CI-Bench.


### Components of a YAML file

Each task is a single YAML file with four top-level sections:

1. `tool_name` – name for the tool
2. `parameters` – all variables your commands need (plus working_directory and venv_name)
3. `setup_commands` – how to prepare the environment (conda or python virtual env)
4. `run_commands` - how to run the tool

### Quick Example (For SWE-Agent)

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
    - python3 -m pip install --upgrade pip && pip install --editable .
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

### Building a YAML File for a tool

1. ***Identify the commands***

Go to the `README` file of your intended tool and find out the command which is used to setup and execute the tool on a particular artifact.

The list of `README`'s of the tools used here:
 - [SWE-agent](tools/swe-agent/README.md).
 - [Agentless](tools/agentless/README.md).
 - [AutoCodeRover](tools/auto-code-rover/README.md)

At first, we have to create the environment for setting up. The `setup_commands` will include setting up the environment. So for both 
`conda` and python virtual environment (which we name it `python`). 

For conda, you have to check whether the tool has `environment.yml` file or not. If there is `environment.yml` file(for swe-agent, auto-code-rover), the user needs to look at the file and take the name of the environment name so that 
user can create the conda environment

```bash
conda env create -f environment.yml
conda activate <venv_name>
```

if `environment.yml` is not present(for `agentless` tool), we have to use
```bash
conda create -n <venv_name> python=<python_version>
conda activate <venv_name>
```

For python virtual environment, The commands are pretty common and the commands are
```bash
python3 -m venv <venv_name>
source <venv_name>/bin/activate
```

From the README, we need to find out the installation command other than environment construction and put it after the environment
construction command list.

After the environment reconstruction and installation, we will include token setup here. We will setup necessary token setup command here.

At last we will add 
```bash
./setup.sh
```

After the setup command, we need to identify the command which is used to run the tool on a bugswarm artifact. The sample command from SWE-Agent `README`

```bash
python3 run.py --model_name gpt4o --config_file config.yml --per_instance_cost_limit 2.0 --bugswarm_image asc_ppp-12345567
```

we have to put it under the `run_commands`

2. ***Identify the parameters***

From the commands, we have to identify the parameters. The parameters will be replaced by placeholders in the `setup_commands` and `run_commands`. The placeholder name will be exactly the same as the key of the parameters. Lets consider the `run_command` of SWE-Agent:

```bash
python3 run.py --model_name gpt4o --config_file config.yml --per_instance_cost_limit 2.0 --bugswarm_image asc_ppp-12345567
```

The command has four variables - `model_name`, `config_file`, `per_instance_cost_limit` and `bugswarm_image`, their values are
`gpt4o`, `config.yml`, `2.0` and `asc_ppp-12345567`. So from this command, we identify the key and value for `paramters` and put 
it under that. First we need to put the placeholder to replace the values and the placeholders will be used as keys of the parameters.

```bash
python3 run.py --model_name <model_name> --config_file <config_file_path> --per_instance_cost_limit <per_instance_cost_limit> --bugswarm_image <bugswarm_artifact>
```

The placeholders naming has no restriction and user has full independence to rename the placeholder name(only exception is bugswarm_artifact). Just the user needs to ensure the placeholder name is as same as key at parameters. So the keys from the run command will be `model_name`, `config_file_path` and `per_instance_cost_limit`. We will leave out the `bugswarm_artifact` as parameter. For all tools, the placeholder must be `bugswarm_artifact`.

We have to find out the parameters from the `setup_commands` as well. Other than the parameters found from the commands, we have to add
two addtional keys - `working_directory` and `venv_name`. Although `venv_name` may be extracted out from the `setup_command`.

From the example, the parametres will look like

```bash
parameters:
  config_file_path: config/default_from_url.yaml
  cost: 2.0
  model_name: gpt4o
  working_directory: swe-agent
  bugswarm_token: <token>
  openai_token: <token>
  anthropic_token: <token>
  together_token: <token>
  venv_name: swe-agent
```

For bugswarm token, please contact with us with email.

You can add other api tokens as well as per tool's usage. 



<!-- From the command, we can see that the model name, config file path, per_instance_cost_limit and the bugswarm_image name can be varied. So we can put these variables under parameters. For parameters, we will leave the `bugswarm_artifact` as it will come from the framework command line. 

For parameters section, mention all the variables from the tool run command. Parameters keys should be as same as inside the command. Lets say, model_name is a parametre here. We have to keep the same `<model_name>` where we will use in the command. So we have to find out the variables from the command and put it in the parameters section. Parametre section also include the `working_directory` and `venv_name` as well. 

if you have `environment.yml` file, please keep the environment name same as yaml file. It is only for `conda` options where most of the time `environment.yml` file is present
 
And before running, please replace the necessary tokens inside the parameters

For `setup_commands`, we have two options. If anyone prefers to run on a conda environment, one should list all the virtual envionment related commands inside the `conda` sections. And if anyone wants to use `venv` command to create virtual
environment, one has to use the commands `python` sections.

Docker commands will be also included here. `run_commands` include necessary commands to run. -->