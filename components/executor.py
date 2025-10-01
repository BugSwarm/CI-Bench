import docker
from docker.errors import APIError
import re
from bugswarm.common.rest_api.database_api import DatabaseAPI
import sys
import subprocess
import os
# from dotenv import load_dotenv

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
    

def is_bugswarm_artifact_name(bugswarm_image: str) -> bool:
    pattern = r'^[a-zA-Z0-9_\-]+-(\d+)'
    match = re.match(pattern, bugswarm_image)
    if match:
        return True
    else:
        return False
    
def extract_folder_and_file(container_name: str, target_path: str):
    try:
        # Initialize Docker client
        client = docker.from_env()

        # Get the container instance
        container = client.containers.get(container_name)

        # Run a shell command in the container to list the directory contents
        command = f"ls {target_path}"
        target_output = container.exec_run(command).output.decode('utf-8').strip()

        # Extract the folder at the target path
        folder_name = target_output.splitlines()[0]  # Assumes there's only one folder
        folder_path = f"{target_path}/{folder_name}"

        # List contents of the subdirectory
        command = f"ls {folder_path}"
        folder_output = container.exec_run(command).output.decode('utf-8').strip()

        # Filter and collect required items ("requirements.zip" is optional)
        items = folder_output.splitlines()
        if "requirements.zip" in items:
            items.remove("requirements.zip")

        return folder_name, items[0]
    
    except docker.errors.NotFound:
        return f"Container '{container_name}' not found."
    except docker.errors.APIError as e:
        return f"Docker API error: {e}"
    except Exception as e:
        return f"An error occurred: {e}"

def execute(container_id, ci_service):
    client = docker.from_env()
    try:
        exit_code, output = client.containers.get(container_id).exec_run("run_failed.sh", user=ci_service)
        output = output.decode().strip()
        
        if output.endswith("Done. Your build exited with 1."):
            print("Not successful")
        elif output.endswith("Done. Your build exited with 0."):
            print(output)
            print("Successful")
        else:
            print("Unexpected output:", output)
        
    except Exception as e:
        print(f"Error executing command: {e}")


def is_container_running(container_name):
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

def copy_and_apply_patch_in_container(container_id: str, patch_file_path: str, commit_sha: str, ci_service:str, user:str, repo:str):
    client = docker.from_env()
    try:
        # client.api.put_archive(container_id, f"/home/{ci_service}/build/failed/{user}/{repo}", open(patch_file_path, "rb"))
        cmd = f"docker cp {patch_file_path} {container_id}:/home/{ci_service}/build/failed/{user}/"
        subprocess.run(cmd, shell=True)
        patch_file = os.path.basename(patch_file_path)
        # Construct the command to run inside the container
        command = f"bash -c 'cd /home/{ci_service}/build/failed/{user}/{repo}/ && git clean -fd && git reset --hard {commit_sha} && cp ../{patch_file} . && git apply {patch_file}'"
        
        # Execute the command inside the container as user 'travis'
        exit_code, output = client.containers.get(container_id).exec_run(command, user=ci_service)
        
        if exit_code == 0:
            print("Patch applied successfully inside the container.")
        else:
            print(f"Error applying patch inside the container: {output.decode()}")
    except Exception as e:
        print(f"Error executing command in container: {e}")


def main(patch_path, artifact_name):
    # load_dotenv()
    bugswarm_token = os.getenv("BUGSWARM_TOKEN")
    # bugswarm_token = "Token"
    bugswarm_api = DatabaseAPI(token=bugswarm_token)
    artifact = bugswarm_api.find_artifact(artifact_name)
    artifact = artifact.json()
    # print(artifact)
    ci_service = artifact["ci_service"]
    commit_sha = artifact["failed_job"]["trigger_sha"]
    try:
        client = docker.from_env()
        if not is_container_running(artifact_name):
            image_tag_full = 'bugswarm/cached-images:{}'.format(artifact_name)
            if not is_docker_image_present(image_tag_full):
                client.images.pull(image_tag_full)
            client.containers.run(image_tag_full, detach=True, name=artifact_name, command='tail -f /dev/null')
        container = client.containers.get(artifact_name)
        container_id = container.id
        target_path = f"/home/{ci_service}/build/failed/"
        user, repo = extract_folder_and_file(artifact_name, target_path)
        copy_and_apply_patch_in_container(container_id, patch_path, commit_sha, ci_service, user, repo)
        execute(container_id, ci_service)
    except Exception as e:
        print(e)

if __name__ == "__main__":
    patch_path = sys.argv[1]
    bugswarm_artifact = sys.argv[2]
    main(patch_path, bugswarm_artifact)