#!/bin/bash

BUGSWARM_TOKEN=""
is_docker_image_present() {
    image_name="$1"
    
    # Check if the image exists using `docker images -q`
    if [[ -n $(docker images -q "$image_name" 2>/dev/null) ]]; then
        return 0  # Image exists (success)
    else
        return 1  # Image does not exist (failure)
    fi
}


is_container_running() {
    container_name="$1"

    # Check if the container is running
    if [[ $(docker ps -q -f "name=^${container_name}$") ]]; then
        return 0  # Container is running (success)
    else
        return 1  # Container is not running (failure)
    fi
}


get_patch_content() {
    artifact_name="$1"
    patch_file_path="$2"
    ci_service="$3"

    image_tag_full="bugswarm/cached-images:${artifact_name}"
    if is_docker_image_present "$image_name"; then
        echo "Docker image $image_name is present."
    else
        echo "Docker image $image_name is not present."
        docker pull "$image_tag_full"
    fi
    # docker pull "$image_tag_full"

    if is_container_running "$container_name"; then
        echo "Docker container $container_name is running."
    else
        echo "Docker container $container_name is not running."
        docker run -d --name "$artifact_name" "$image_tag_full" tail -f /dev/null
    fi
    
    container_id=$(docker ps -aqf "name=${artifact_name}")
    echo "$container_id"
    mkdir -p project_path
    docker cp ${container_id}:/home/${ci_service}/build/failed project_path
    docker cp ${container_id}:/home/${ci_service}/build/passed project_path
    
    cp "$patch_file_path" model.patch
}

extract_folder() {
    target_path="$1"
    folder_name=$(ls "$target_path" | head -n 1)
    folder_path="$target_path/$folder_name"
    
    items=$(ls "$folder_path" | grep -v "requirements.zip" | head -n 1)
    echo "$folder_name" "$items"
}

run() {
    bugswarm_artifact="$1"
    patch_file_path="$2"
    evaluation_metric="$3"
    
    ci_service=$(curl -sLH "Authorization: token $BUGSWARM_TOKEN" "http://www.api.bugswarm.org/v1/artifacts/$bugswarm_artifact" | yq -r .ci_service)
    echo "$ci_service"
    get_patch_content "$bugswarm_artifact" "$patch_file_path" "$ci_service"
    read f1 f2 < <(extract_folder "project_path/failed/")
    
    failed_file=""
    passed_file=""

    while IFS= read -r line; do
        if [[ $line == diff* ]]; then
            failed_file=$(echo "$line" | awk '{print $3}' | cut -d'/' -f2-)
            passed_file=$(echo "$line" | awk '{print $4}' | cut -d'/' -f2-)
            break
        fi
    done < model.patch
    echo "$failed_file"

    if [[ -f "project_path/failed/${f1}/${f2}/model.patch" ]]; then
        rm project_path/failed/${f1}/${f2}/model.patch
    fi
    cp model.patch project_path/failed/${f1}/${f2}/

    cd project_path/failed/${f1}/${f2}/ && git apply model.patch
    cd ../../../../

    full_failed_file_path="project_path/failed/${f1}/${f2}/${failed_file}"
    full_passed_file_path="project_path/passed/${f1}/${f2}/${passed_file}"
    
    echo "$full_failed_file_path"
    echo "$full_passed_file_path"
    if [ "$evaluation_metric" == "AST" ]; then
        cmd="python3 Evaluation/AST/evaluate.py $full_failed_file_path $full_passed_file_path ."
        read f < <($cmd)
    elif [ "$evaluation_metric" == "SYE" ]; then
        read f < <(python3 Evaluation/SYE/sye.py "$full_failed_file_path" "$full_passed_file_path" .)
    fi

    echo "$f"
    rm -rf project_path/failed/
    rm -rf project_path/passed/
    rm model.patch
}

main() {
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            --evaluation-metric)
                EVAL="$2"
                shift 2
                ;;
            --tool-name)
                TOOL_NAME="$2"
                shift 2
                ;;
            --artifact-id)
                bugswarm_artifact="$2"
                shift 2
                ;;
            --patch-file-path)
                PATCH="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    run "$bugswarm_artifact" "$PATCH" "$EVAL" "$TOOL_NAME"
}

main "$@"

