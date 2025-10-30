#!/bin/bash

run_command() {
    task="$1"
    tool_name="$2"
    setup="$3"
    venv_setup="$4"
    # run="$5"
    yaml_file="task/$task/$tool_name.yaml"
    echo "$yaml_file"

    if [ ! -f "$yaml_file" ]; then
        echo "YAML file not found: $yaml_file"
        exit 1
    fi

    declare -A parameters
    while IFS=": " read -r key value; do
        parameters["$key"]="$value"
    done < <(yq e '.parameters | to_entries | .[] | "\(.key):\(.value)"' "$yaml_file")

    echo "Parameters:"
    for key in "${!parameters[@]}"; do
        echo "$key: ${parameters[$key]}"
    done

    env_name=$(yq e '.parameters.venv_name' "$yaml_file")
    echo "$env_name"
    working_directory=$(yq e '.parameters.working_directory' "$yaml_file")

    if [[ "$virtual_env" == "python" ]]; then
        mapfile -t commands < <(yq e '.setup_commands.python[]' "$yaml_file")
    elif [[ "$virtual_env" == "conda" ]]; then
        if ! command -v conda &> /dev/null; then
            echo "Conda is not installed right now. Please install it and try again"
            exit 1
        fi
        conda_addr=$(conda info | awk -F ': ' '/base environment/ {print $2}' | awk '{print $1}')
        source $conda_addr/etc/profile.d/conda.sh
        mapfile -t commands < <(yq e '.setup_commands.conda[]' "$yaml_file")
    else
        echo "Please define the virtual environment."
        exit 1
    fi
    

    cd $working_directory
    for i in "${!commands[@]}"; do
        command="${commands[i]}"

        for key in "${!parameters[@]}"; do
            placeholder="<${key}>"
            command="${command//$placeholder/${parameters[$key]}}"
        done
        echo "$command"
        eval "$command"

        if [[ $? -ne 0 ]]; then
            echo "Error: Command '$command' failed. Exiting."
            exit 1
        fi
    done


}

help_message() {
    echo "Usage: $0 --task <task_name> --tool-name <tool_name> --virtual-env <virtual_env>"
    echo "Options:"
    echo "  --task <task_name>                Name of the benchmarking task."
    echo "  --tool-name <tool_name>           Target tool name for benchmarking."
    echo "  --virtual-env <virtual_env>       Virtual environment option, can be conda or python."
}

main() {
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            --task)
                TASK="$2"
                shift 2
                ;;
            --tool-name)
                TOOL_NAME="$2"
                shift 2
                ;;
            --virtual-env)
                virtual_env="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                help_message
                exit 1
                ;;
        esac
    done

    if [[ -z "$TASK" || -z "$TOOL_NAME" || -z "$virtual_env" ]]; then
        help_message
        exit 1
    fi

    run_command "$TASK" "$TOOL_NAME" "$VENV_SETUP"
}

main "$@"

