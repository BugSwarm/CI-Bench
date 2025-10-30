import subprocess
import sys
import os

def check_ast_change(file1, file2):
    try:
        result = subprocess.run(
            ["java", "-jar", "gumtree-spoon-ast-diff-1.92-jar-with-dependencies.jar", file1, file2],
            text=True,
            capture_output=True
        )
        
        if "no AST change" in result.stdout:
            return "yes"
        else:
            return "no"
    except Exception as e:
        print(f"An error occurred: {e}")
        return None


file1 = sys.argv[1]
file2 = sys.argv[2]
working_directory = sys.argv[3]

if __name__ == "__main__":
    file_path_1 = os.path.join(working_directory, file1)
    file_path_2 = os.path.join(working_directory, file2)
    ast_changed = check_ast_change(file_path_1, file_path_2)
    print(ast_changed)
    if ast_changed is None:
        print("Unable to determine AST changes due to an error.")
