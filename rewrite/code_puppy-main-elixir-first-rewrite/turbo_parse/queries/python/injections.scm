; Language injection queries for Python
; Based on Helix Editor injection patterns

; SQL in triple-quoted strings with context
(expression_statement
  (assignment
    left: (identifier) @var_name
    right: (string) @injection.content
    (#match? @var_name "^[qQ][uU][eE][rR][yY]|[sS][qQ][lL]|[cC][uU][rR][sS][oO][rR]|[dD][bB]$")))

; HTML in strings
(string) @injection.content
(#match? @injection.content "^\"\"\"<|^'''<")
(#set! injection.language "html")

; JSON in strings (heuristic based on content)
(string) @injection.content
(#match? @injection.content "^\"\"\"\\s*\\{|^'''\\s*\\{")
(#set! injection.language "json")

; Regex in raw strings
(string) @injection.content
(#match? @injection.content "^r[\"']")
(#set! injection.language "regex")
