; Language injection queries for Elixir
; Based on Helix Editor injection patterns

; HEEx sigil support
(sigil
  (sigil_name) @injection.language
  (quoted_content) @injection.content
  (#match? @injection.language "^H$")
  (#set! injection.language "heex"))

; EEx template in ~E sigil
(sigil
  (sigil_name) @injection.language
  (quoted_content) @injection.content
  (#match? @injection.language "^E$")
  (#set! injection.language "eex"))

; SQL in sigils
(sigil
  (sigil_name) @injection.language
  (quoted_content) @injection.content
  (#match? @injection.language "^[sS][qQ][lL]$")
  (#set! injection.language "sql"))

; JSON in sigils
(sigil
  (sigil_name) @injection.language
  (quoted_content) @injection.content
  (#match? @injection.language "^[jJ][sS][oO][nN]$")
  (#set! injection.language "json"))
