import ast
import glob
import pathlib
import re
import javalang
from dataclasses import dataclass
from os.path import join as pjoin

from app import utils as apputils


@dataclass
class SearchResult:
    """Dataclass to hold search results."""

    file_path: str  # this is absolute path
    class_name: str | None
    func_name: str | None
    code: str

    def to_tagged_upto_file(self, project_root: str):
        """Convert the search result to a tagged string, upto file path."""
        rel_path = apputils.to_relative_path(self.file_path, project_root)
        file_part = f"<file>{rel_path}</file>"
        return file_part

    def to_tagged_upto_class(self, project_root: str):
        """Convert the search result to a tagged string, upto class."""
        prefix = self.to_tagged_upto_file(project_root)
        class_part = (
            f"<class>{self.class_name}</class>" if self.class_name is not None else ""
        )
        return f"{prefix}\n{class_part}"

    def to_tagged_upto_func(self, project_root: str):
        """Convert the search result to a tagged string, upto function."""
        prefix = self.to_tagged_upto_class(project_root)
        func_part = (
            f" <func>{self.func_name}</func>" if self.func_name is not None else ""
        )
        return f"{prefix}{func_part}"

    def to_tagged_str(self, project_root: str):
        """Convert the search result to a tagged string."""
        prefix = self.to_tagged_upto_func(project_root)
        code_part = f"<code>\n{self.code}\n</code>"
        return f"{prefix}\n{code_part}"

    @staticmethod
    def collapse_to_file_level(lst, project_root: str) -> str:
        """Collapse search results to file level."""
        res = dict()  # file -> count
        for r in lst:
            if r.file_path not in res:
                res[r.file_path] = 1
            else:
                res[r.file_path] += 1
        res_str = ""
        for file_path, count in res.items():
            rel_path = apputils.to_relative_path(file_path, project_root)
            file_part = f"<file>{rel_path}</file>"
            res_str += f"- {file_part} ({count} matches)\n"
        return res_str

    @staticmethod
    def collapse_to_method_level(lst, project_root: str) -> str:
        """Collapse search results to method level."""
        res = dict()  # file -> dict(method -> count)
        for r in lst:
            if r.file_path not in res:
                res[r.file_path] = dict()
            func_str = r.func_name if r.func_name is not None else "Not in a function"
            if func_str not in res[r.file_path]:
                res[r.file_path][func_str] = 1
            else:
                res[r.file_path][func_str] += 1
        res_str = ""
        for file_path, funcs in res.items():
            rel_path = apputils.to_relative_path(file_path, project_root)
            file_part = f"<file>{rel_path}</file>"
            for func, count in funcs.items():
                if func == "Not in a function":
                    func_part = func
                else:
                    func_part = f" <func>{func}</func>"
                res_str += f"- {file_part}{func_part} ({count} matches)\n"
        return res_str


def find_java_files(dir_path: str) -> list[str]:
    """Get all .java files recursively from a directory.

    Skips files that are obviously not from the source code, such third-party library code.

    Args:
        dir_path (str): Path to the directory.
    Returns:
        List[str]: List of .py file paths. These paths are ABSOLUTE path!
    """
    java_files = glob.glob(pjoin(dir_path, "**/*.java"), recursive=True)
    res = []
    for file in java_files:
        rel_path = file[len(dir_path) + 1:]
        if rel_path.startswith("build"):
            continue
        if rel_path.startswith("doc"):
            continue
        if rel_path.startswith("lib") or rel_path.startswith("third_party"):
            # Skip third-party library code
            continue
        if rel_path.startswith("testdata") or rel_path.startswith("examples"):
            # Skip test data or example code
            continue
        if rel_path.startswith("out") or rel_path.startswith("generated"):
            # Skip output or generated files
            continue
        res.append(file)
    return res

def parse_java_file(file_full_path: str) -> tuple[list, dict, list] | None:
    try:
        file_content = pathlib.Path(file_full_path).read_text()
        tree = javalang.parse.parse(file_content)
    except:
        return None
    
    classes = []
    class_to_methods = {}
    top_level_methods = []
    
    for path, node in tree.filter(javalang.tree.ClassDeclaration):
        class_name = node.name
        start_lineno = node.position.line if node.position else None
        classes.append((class_name, start_lineno, None))
        
        methods = []
        for member in node.body:
            if isinstance(member, javalang.tree.MethodDeclaration):
                method_name = member.name
                start_lineno = member.position.line if member.position else None
                methods.append((method_name, start_lineno, None))
        class_to_methods[class_name] = methods
        
    for member in tree.types:
        if isinstance(member, javalang.tree.MethodDeclaration):
            method_name = member.name
            start_lineno = member.position.line if member.position else None
            top_level_methods.append((method_name, start_lineno, None))

    return classes, class_to_methods, top_level_methods
    

def get_func_snippet_in_class_for_java(
    file_full_path: str, class_name: str, func_name: str, include_lineno=False
) -> str | None:
    try:
        with open(file_full_path, "r") as f:
            file_content = f.read()

        # Parse the file content
        tree = javalang.parse.parse(file_content)
        lines = file_content.splitlines()

        # Find the specified class
        for path, node in tree.filter(javalang.tree.ClassDeclaration):
            if node.name == class_name:
                # Find the specified method within the class
                for member in node.body:
                    if (
                        isinstance(member, javalang.tree.MethodDeclaration)
                        and member.name == func_name
                    ):
                        start_lineno = member.position.line - 1  # Convert to 0-based index
                        # Determine end line by identifying the closing bracket
                        if member.body:
                            end_lineno = start_lineno + len(member.body) + 1
                        else:
                            end_lineno = start_lineno + 1

                        # Extract the snippet
                        if include_lineno:
                            snippet = [
                                f"{i + 1}: {line}"
                                for i, line in enumerate(
                                    lines[start_lineno:end_lineno]
                                )
                            ]
                            return "\n".join(snippet)
                        else:
                            return "\n".join(lines[start_lineno:end_lineno])

    except Exception as e:
        # Handle errors (e.g., file read or parse failures)
        print(f"Error: {e}")
        return None

    # Class or method not found
    return None

def find_python_files(dir_path: str) -> list[str]:
    """Get all .py files recursively from a directory.

    Skips files that are obviously not from the source code, such third-party library code.

    Args:
        dir_path (str): Path to the directory.
    Returns:
        List[str]: List of .py file paths. These paths are ABSOLUTE path!
    """

    py_files = glob.glob(pjoin(dir_path, "**/*.py"), recursive=True)
    res = []
    for file in py_files:
        rel_path = file[len(dir_path) + 1 :]
        if rel_path.startswith("build"):
            continue
        if rel_path.startswith("doc"):
            # discovered this issue in 'pytest-dev__pytest'
            continue
        if rel_path.startswith("requests/packages"):
            # to walkaround issue in 'psf__requests'
            continue
        if (
            rel_path.startswith("tests/regrtest_data")
            or rel_path.startswith("tests/input")
            or rel_path.startswith("tests/functional")
        ):
            # to walkaround issue in 'pylint-dev__pylint'
            continue
        if rel_path.startswith("tests/roots") or rel_path.startswith(
            "sphinx/templates/latex"
        ):
            # to walkaround issue in 'sphinx-doc__sphinx'
            continue
        if rel_path.startswith("tests/test_runner_apps/tagged/") or rel_path.startswith(
            "django/conf/app_template/"
        ):
            # to walkaround issue in 'django__django'
            continue
        res.append(file)
    return res


def parse_python_file(file_full_path: str) -> tuple[list, dict, list] | None:
    """
    Main method to parse AST and build search index.
    Handles complication where python ast module cannot parse a file.
    """
    try:
        file_content = pathlib.Path(file_full_path).read_text()
        tree = ast.parse(file_content)
    except Exception:
        # failed to read/parse one file, we should ignore it
        return None

    # (1) get all classes defined in the file
    classes = []
    # (2) for each class in the file, get all functions defined in the class.
    class_to_funcs = {}
    # (3) get top-level functions in the file (exclues functions defined in classes)
    top_level_funcs = []

    function_nodes_in_class = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            ## class part (1): collect class info
            class_name = node.name
            start_lineno = node.lineno
            end_lineno = node.end_lineno
            # line numbers are 1-based
            classes.append((class_name, start_lineno, end_lineno))

            ## class part (2): collect function info inside this class
            class_funcs = []
            for n in ast.walk(node):
                if isinstance(n, ast.FunctionDef):
                    class_funcs.append((n.name, n.lineno, n.end_lineno))
                    function_nodes_in_class.append(n)
            class_to_funcs[class_name] = class_funcs

        # top-level functions, excluding functions defined in classes
        elif isinstance(node, ast.FunctionDef) and node not in function_nodes_in_class:
            function_name = node.name
            start_lineno = node.lineno
            end_lineno = node.end_lineno
            # line numbers are 1-based
            top_level_funcs.append((function_name, start_lineno, end_lineno))

    return classes, class_to_funcs, top_level_funcs


def get_func_snippet_in_class(
    file_full_path: str, class_name: str, func_name: str, include_lineno=False
) -> str | None:
    """Get actual function source code in class.

    All source code of the function is returned.
    Assumption: the class and function exist.
    """
    with open(file_full_path) as f:
        file_content = f.read()

    tree = ast.parse(file_content)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for n in ast.walk(node):
                if isinstance(n, ast.FunctionDef) and n.name == func_name:
                    start_lineno = n.lineno
                    end_lineno = n.end_lineno
                    assert end_lineno is not None, "end_lineno is None"
                    if include_lineno:
                        return get_code_snippets_with_lineno(
                            file_full_path, start_lineno, end_lineno
                        )
                    else:
                        return get_code_snippets(
                            file_full_path, start_lineno, end_lineno
                        )
    # In this file, cannot find either the class, or a function within the class
    return None


def get_code_region_containing_code(
    file_full_path: str, code_str: str
) -> list[tuple[int, str]]:
    """In a file, get the region of code that contains a specific string.

    Args:
        - file_full_path: Path to the file. (absolute path)
        - code_str: The string that the function should contain.
    Returns:
        - A list of tuple, each of them is a pair of (line_no, code_snippet).
        line_no is the starting line of the matched code; code snippet is the
        source code of the searched region.
    """
    with open(file_full_path) as f:
        file_content = f.read()

    context_size = 3
    # since the code_str may contain multiple lines, let's not split the source file.

    # we want a few lines before and after the matched string. Since the matched string
    # can also contain new lines, this is a bit trickier.
    pattern = re.compile(re.escape(code_str))
    # each occurrence is a tuple of (line_no, code_snippet) (1-based line number)
    occurrences: list[tuple[int, str]] = []
    file_content_lines = file_content.splitlines()
    for match in pattern.finditer(file_content):
        matched_start_pos = match.start()
        # first, find the line number of the matched start position (0-based)
        matched_line_no = file_content.count("\n", 0, matched_start_pos)

        window_start_index = max(0, matched_line_no - context_size)
        window_end_index = min(
            len(file_content_lines), matched_line_no + context_size + 1
        )

        context = "\n".join(file_content_lines[window_start_index:window_end_index])
        occurrences.append((matched_line_no, context))

    return occurrences


def get_func_snippet_with_code_in_file(file_full_path: str, code_str: str) -> list[str]:
    """In a file, get the function code, for which the function contains a specific string.

    Args:
        file_full_path (str): Path to the file. (absolute path)
        code_str (str): The string that the function should contain.

    Returns:
        A list of code snippets, each of them is the source code of the searched function.
    """
    with open(file_full_path) as f:
        file_content = f.read()

    tree = ast.parse(file_content)
    all_snippets = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        func_start_lineno = node.lineno
        func_end_lineno = node.end_lineno
        assert func_end_lineno is not None
        func_code = get_code_snippets(
            file_full_path, func_start_lineno, func_end_lineno
        )
        # This func code is a raw concatenation of source lines which contains new lines and tabs.
        # For the purpose of searching, we remove all spaces and new lines in the code and the
        # search string, to avoid non-match due to difference in formatting.
        stripped_func = " ".join(func_code.split())
        stripped_code_str = " ".join(code_str.split())
        if stripped_code_str in stripped_func:
            all_snippets.append(func_code)

    return all_snippets

def get_func_snippet_with_code_in_file_for_java(file_full_path: str, code_str: str) -> list[str]:
    try:
        with open(file_full_path, "r") as f:
            file_content = f.read()

        # Parse the file content
        tree = javalang.parse.parse(file_content)
        lines = file_content.splitlines()

        matched_snippets = []

        # Iterate over all method declarations
        for path, node in tree.filter(javalang.tree.MethodDeclaration):
            if node.body:
                # Extract method start and end lines
                start_lineno = node.position.line - 1  # Convert to 0-based index
                # Approximate end line by checking body length
                end_lineno = start_lineno + len(node.body) + 1

                # Extract method source code
                func_code = "\n".join(lines[start_lineno:end_lineno])

                # Normalize the code for searching
                stripped_func = " ".join(func_code.split())
                stripped_code_str = " ".join(code_str.split())

                # Check if the provided code string exists in the method
                if stripped_code_str in stripped_func:
                    matched_snippets.append(func_code)

        return matched_snippets

    except Exception as e:
        # Handle errors gracefully
        print(f"Error: {e}")
        return []


def get_code_snippets_with_lineno(file_full_path: str, start: int, end: int) -> str:
    """Get the code snippet in the range in the file.

    The code snippet should come with line number at the beginning for each line.

    TODO: When there are too many lines, return only parts of the output.
          For class, this should only involve the signatures.
          For functions, maybe do slicing with dependency analysis?

    Args:
        file_path (str): Path to the file.
        start (int): Start line number. (1-based)
        end (int): End line number. (1-based)
    """
    with open(file_full_path) as f:
        file_content = f.readlines()

    snippet = ""
    for i in range(start - 1, end):
        snippet += f"{i+1} {file_content[i]}"
    return snippet


def get_code_snippets(file_full_path: str, start: int, end: int) -> str:
    """Get the code snippet in the range in the file, without line numbers.

    Args:
        file_path (str): Full path to the file.
        start (int): Start line number. (1-based)
        end (int): End line number. (1-based)
    """
    with open(file_full_path) as f:
        file_content = f.readlines()
    snippet = ""
    for i in range(start - 1, end):
        snippet += file_content[i]
    return snippet


def extract_func_sig_from_ast(func_ast: ast.FunctionDef) -> list[int]:
    """Extract the function signature from the AST node.

    Includes the decorators, method name, and parameters.

    Args:
        func_ast (ast.FunctionDef): AST of the function.

    Returns:
        The source line numbers that contains the function signature.
    """
    func_start_line = func_ast.lineno
    if func_ast.decorator_list:
        # has decorators
        decorator_start_lines = [d.lineno for d in func_ast.decorator_list]
        decorator_first_line = min(decorator_start_lines)
        func_start_line = min(decorator_first_line, func_start_line)
    # decide end line from body
    if func_ast.body:
        # has body
        body_start_line = func_ast.body[0].lineno
        end_line = body_start_line - 1
    else:
        # no body
        end_line = func_ast.end_lineno
    assert end_line is not None
    return list(range(func_start_line, end_line + 1))


def extract_class_sig_from_ast(class_ast: ast.ClassDef) -> list[int]:
    """Extract the class signature from the AST.

    Args:
        class_ast (ast.ClassDef): AST of the class.

    Returns:
        The source line numbers that contains the class signature.
    """
    # STEP (1): extract the class signature
    sig_start_line = class_ast.lineno
    if class_ast.body:
        # has body
        body_start_line = class_ast.body[0].lineno
        sig_end_line = body_start_line - 1
    else:
        # no body
        sig_end_line = class_ast.end_lineno
    assert sig_end_line is not None
    sig_lines = list(range(sig_start_line, sig_end_line + 1))

    # STEP (2): extract the function signatures and assign signatures
    for stmt in class_ast.body:
        if isinstance(stmt, ast.FunctionDef):
            sig_lines.extend(extract_func_sig_from_ast(stmt))
        elif isinstance(stmt, ast.Assign):
            # for Assign, skip some useless cases where the assignment is to create docs
            stmt_str_format = ast.dump(stmt)
            if "__doc__" in stmt_str_format:
                continue
            # otherwise, Assign is easy to handle
            assert stmt.end_lineno is not None
            assign_range = list(range(stmt.lineno, stmt.end_lineno + 1))
            sig_lines.extend(assign_range)

    return sig_lines


def extract_func_sig_from_java(method_node: javalang.tree.MethodDeclaration, lines: list[str]) -> list[int]:
    try:
        # Start with the method declaration line
        start_line = method_node.position.line - 1  # Convert to 0-based index
        signature_lines = [start_line]

        # Check for annotations (decorators in Python equivalent)
        if hasattr(method_node, 'annotations') and method_node.annotations:
            for annotation in method_node.annotations:
                annotation_line = annotation.position.line - 1
                signature_lines.append(annotation_line)

        # Include lines up to the method body opening brace '{'
        current_line = start_line
        while current_line < len(lines):
            if '{' in lines[current_line]:  # Stop at the body start
                break
            signature_lines.append(current_line)
            current_line += 1

        # Deduplicate and sort
        return sorted(set(signature_lines))
    except Exception as e:
        print(f"Error extracting function signature: {e}")
        return []


def extract_class_sig_from_java(class_node: javalang.tree.ClassDeclaration, lines: list[str]) -> list[int]:
    try:
        # Start with the class declaration line
        start_line = class_node.position.line - 1  # Convert to 0-based index
        signature_lines = [start_line]

        # Check for annotations (decorators in Python equivalent)
        if hasattr(class_node, 'annotations') and class_node.annotations:
            for annotation in class_node.annotations:
                annotation_line = annotation.position.line - 1
                signature_lines.append(annotation_line)

        # Add constructor and method signatures
        for member in class_node.body:
            if isinstance(member, javalang.tree.MethodDeclaration):
                signature_lines.extend(extract_func_sig_from_java(member, lines))
            elif isinstance(member, javalang.tree.ConstructorDeclaration):
                signature_lines.extend(extract_func_sig_from_java(member, lines))

        # Include the opening brace '{' of the class
        current_line = start_line
        while current_line < len(lines):
            if '{' in lines[current_line]:  # Stop at the body start
                signature_lines.append(current_line)
                break
            current_line += 1

        # Deduplicate and sort
        return sorted(set(signature_lines))
    except Exception as e:
        print(f"Error extracting class signature: {e}")
        return []

def get_class_signature(file_full_path: str, class_name: str) -> str:
    """Get the class signature.

    Args:
        file_path (str): Path to the file.
        class_name (str): Name of the class.
    """
    with open(file_full_path) as f:
        file_content = f.read()

    tree = ast.parse(file_content)
    relevant_lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # we reached the target class
            relevant_lines = extract_class_sig_from_ast(node)
            break
    if not relevant_lines:
        return ""
    else:
        with open(file_full_path) as f:
            file_content = f.readlines()
        result = ""
        for line in relevant_lines:
            line_content: str = file_content[line - 1]
            if line_content.strip().startswith("#"):
                # this kind of comment could be left until this stage.
                # reason: # comments are not part of func body if they appear at beginning of func
                continue
            result += line_content
        return result


def get_class_signature_for_java(file_full_path: str, class_name: str) -> str:
    with open(file_full_path, "r") as f:
        file_content = f.read()
        lines = file_content.splitlines()

    try:
        # Parse the file using javalang
        tree = javalang.parse.parse(file_content)

        # Traverse the AST to find the target class
        for path, node in tree.filter(javalang.tree.ClassDeclaration):
            if node.name == class_name:
                # Extract relevant lines for the class signature
                relevant_lines = extract_class_sig_from_java(node, lines)

                if not relevant_lines:
                    return ""
                
                # Combine the extracted lines into the class signature
                result = ""
                for line_num in relevant_lines:
                    line_content = lines[line_num]
                    if line_content.strip().startswith("//"):
                        # Skip comments
                        continue
                    result += line_content + "\n"
                return result

    except javalang.parser.JavaSyntaxError as e:
        print(f"Syntax error while parsing {file_full_path}: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    return ""