from antlr4 import *
from JavaLexer import JavaLexer
from JavaParser import JavaParser
import sys
import os


def read_file(file_path):
    with open(file_path, 'r') as file:
        return file.read()


def tokenize_code(code):
    input_stream = InputStream(code)
    lexer = JavaLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    token_stream.fill() 

    token_list = []

    for token in token_stream.tokens:
        if token.type not in [JavaLexer.WS, JavaLexer.COMMENT]:
            token_list.append((token.type, token.text))

    return token_list


def compare_token_lists(tokens1, tokens2):
    if len(tokens1) != len(tokens2):
        return False

    for t1, t2 in zip(tokens1, tokens2):
        if t1 != t2:
            return False

    return True


def syntactically_equivalent(file1, file2):
    code1 = read_file(file1)
    code2 = read_file(file2)

    tokens1 = tokenize_code(code1)
    tokens2 = tokenize_code(code2)

    return compare_token_lists(tokens1, tokens2)


file1_path = sys.argv[1]
file2_path = sys.argv[2]
working_directory = sys.argv[3]

file_path_1 = os.path.join(working_directory, file1_path)
file_path_2 = os.path.join(working_directory, file2_path)

if syntactically_equivalent(file_path_1, file_path_2):
    print("yes")
else:
    print("no")
