#!/bin/bash

run_command() {
    task="$1"
    tool_name="$2"
    setup="$3"
    venv_setup="$4"
    run="$5"
    yaml_file="task/$task/$tool_name.yaml"
    echo "$yaml_file"

    if [ ! -f "$yaml_file" ]; then
        echo "YAML file not found: $yaml_file"
        exit 1
    fi

    declare -A parameters
    while IFS=": " read -r key value; do
        parameters["$key"]="$value"
    done < <(yq e '.parameters | to_entries | .[] | .key + ": " + .value' "$yaml_file")

    echo "Parameters:"
    for key in "${!parameters[@]}"; do
        echo "$key: ${parameters[$key]}"
    done

    env_name=$(yq e '.parameters.venv_name' "$yaml_file")
    echo "$env_name"
    working_directory=$(yq e '.parameters.working_directory' "$yaml_file")

    if [[ "$virtual_env" == "python" ]]; then
        source "$working_directory/$env_name/bin/activate"
    elif [[ "$virtual_env" == "conda" ]]; then
        if ! command -v conda &> /dev/null; then
            echo "Conda is not installed right now. Please install it and try again"
            exit 1
        fi
        conda_addr=$(conda info | awk -F ': ' '/base environment/ {print $2}' | awk '{print $1}')
        source $conda_addr/etc/profile.d/conda.sh
        conda activate "$env_name"
        if [[ $? -ne 0 ]]; then
            echo "Failed to activate the virtual environment. Exiting..."
            exit 1
        fi
    else
        echo "Please define the virtual environment."
        exit 1
    fi
    mapfile -t commands < <(yq e '.run_commands[]' "$yaml_file")

    artifacts_list=()
    if [ -n "$artifact_id" ]; then
        artifacts_list+=("$artifact_id")
    elif [ -n "$artifact_list" ]; then
        echo "Reading artifact list from file: $artifact_list"
        while IFS= read -r line; do
            trimmed_line=$(echo "$line" | xargs)
            if [[ -n "$trimmed_line" ]]; then
                artifacts_list+=("$trimmed_line")
            fi
        done < "$artifact_list"
    fi

    cd $working_directory
    echo "$working_directory"
    echo "$artifacts_list"
    for artifact in "${artifacts_list[@]}"; do
        for i in "${!commands[@]}"; do
            command="${commands[i]}"
            command=$(echo "$command" | sed "s/<bugswarm_artifact>/$artifact/g")
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
    done


}

help_message() {
    echo "Usage: $0 --task <task_name> --tool-name <tool_name> --virtual-env <virtual_env> [--artifact-id <artifact_id> | --artifact-ist <artifact_list>]"
    echo "Options:"
    echo "  --task <task_name>                Name of the benchmarking task."
    echo "  --tool-name <tool_name>           Target tool name for benchmarking."
    echo "  --virtual-env <virtual_env>       Virtual environment option, can be conda or python."
    echo "  --artifact-id <artifact_id>       ID of the BugSwarm artifact."
    echo "  --artifact-list <artifact_list>   Path to the file containing list of artifact IDs."
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
            --artifact-id)
                artifact_id="$2"
                shift 2
                ;;
            --artifact-list)
                artifact_list="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    # Check if required arguments are provided, if not, print help message
    if [[ -z "$TASK" || -z "$TOOL_NAME" || -z "$virtual_env" ]]; then
        help_message
        exit 1
    fi
    if [[ (-n "$artifact_id" && -n "$artifact_list") || (-z "$artifact_id" && -z "$artifact_list") ]]; then
        echo "Error: Please specify either --artifact-id or --artifact-list."
        help_message
        exit 1
    fi

    run_command "$TASK" "$TOOL_NAME" "$VENV_SETUP"
}

main "$@"
