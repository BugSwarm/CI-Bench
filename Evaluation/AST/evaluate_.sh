#!/bin/bash

# Function to check AST changes using GumTree Spoon AST Diff
check_ast_change() {
    local file1="$1"
    local file2="$2"
    local jar_file="gumtree-spoon-ast-diff-1.92-jar-with-dependencies.jar"
    
    # Run the JAR file with the given files
    result=$(java -jar "$jar_file" "$file1" "$file2" 2>&1)
    
    # Check for errors
    if [ $? -ne 0 ]; then
        echo "An error occurred: $result"
        return 2
    fi
    
    # Check the output for "no AST change"
    if echo "$result" | grep -q "no AST change"; then
        echo "No AST changes detected."
        return 1
    else
        echo "AST changes detected."
        return 0
    fi
}

# Ensure two arguments are provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <file1.java> <file2.java>"
    exit 1
fi

# Run the function
check_ast_change "$1" "$2"
status=$?

if [ $status -eq 2 ]; then
    echo "Unable to determine AST changes due to an error."
fi

exit $status
