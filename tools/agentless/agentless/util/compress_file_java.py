import javalang


class CompressTransformerJava:
    DESCRIPTION = str = "Replaces function/method body with ..."
    replacement_string = '...'
    
    def __init__(self, keep_constant=True):
        self.keep_constant = keep_constant
        
    def transform_class(self, class_node):
        transformed_body = []
        for member in class_node.body:
            if isinstance(member, javalang.tree.MethodDeclaration):
                # Replace method bodies with "..."
                transformed_body.append(f"    {member.name}() {{ {self.replacement_string} }}")
            elif self.keep_constant and isinstance(member, javalang.tree.FieldDeclaration):
                # Keep constant declarations
                transformed_body.append(f"    {member.declarators[0].name} = {self.replacement_string};")
        return {"name": class_node.name, "body": transformed_body}

    def transform(self, java_code):
        try:
            tree = javalang.parse.parse(java_code)
        except javalang.parser.JavaSyntaxError as e:
            return java_code
        
        transformed_code = []
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            transformed_class = self.transform_class(node)
            indent = "    "
            body_code = "\n".join(indent + line for line in transformed_class["body"])
            class_code = f"class {transformed_class['name']} {{\n{body_code}\n}}"
            transformed_code.append(class_code)

        return "\n\n".join(transformed_code)


def get_skeleton_code_java(java_code, keep_constant=True):
    transformer = CompressTransformerJava(keep_constant)
    skeleton_code = transformer.transform(java_code)
    return skeleton_code


if __name__ == "__main__":
    java_code = """
    import java.util.*;

    public class FooClass {
        private int x;

        public FooClass(int x) {
            this.x = x;
        }

        public void print() {
            System.out.println(this.x);
        }
    }

    public class Test {
        public static void main(String[] args) {
            FooClass foo = new FooClass(42);
            foo.print();
        }
    }
    """

    transformer = CompressTransformerJava(keep_constant=True)
    skeleton_code = transformer.transform(java_code)
    print(skeleton_code)
