use std::time::Instant;

fn main() {
    let code = r#"
def hello():
    pass

class Foo:
    def bar(self):
        pass
"#;

    let start = Instant::now();
    
    let mut parser = tree_sitter::Parser::new();
    parser.set_language(&tree_sitter_python::LANGUAGE.into()).unwrap();
    
    let tree = parser.parse(code, None).unwrap();
    let root = tree.root_node();
    
    // Extract function and class names
    let mut symbols = vec![];
    for i in 0..root.child_count() {
        let child = root.child(i).unwrap();
        match child.kind() {
            "function_definition" => {
                if let Some(name_node) = child.child_by_field_name("name") {
                    symbols.push(format!("fn {}", name_node.utf8_text(code.as_bytes()).unwrap()));
                }
            }
            "class_definition" => {
                if let Some(name_node) = child.child_by_field_name("name") {
                    symbols.push(format!("class {}", name_node.utf8_text(code.as_bytes()).unwrap()));
                }
            }
            _ => {}
        }
    }
    
    let elapsed = start.elapsed();
    
    println!("Symbols found:");
    for s in &symbols {
        println!("  - {}", s);
    }
    println!("\nParse time: {:?}", elapsed);
    assert!(elapsed.as_millis() < 5, "Parse took too long!");
}
