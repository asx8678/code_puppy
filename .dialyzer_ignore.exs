# Dialyzer ignore patterns for Mana project
# These are warnings that are either in non-core modules or related to external dependencies

[
  # DynamicSupervisor type is from Elixir standard library
  ~r/unknown_type.*DynamicSupervisor\.on_start/,

  # Mix.Task warnings - expected since Mix is not in PLT
  ~r/callback_info_missing.*Mix\.Task/,
  ~r/unknown_function.*Mix\.Task/,

  # TUI modules are non-critical
  ~r/lib\/mana\/tui\/.*pattern_match/,
  ~r/lib\/mana\/tui\/markdown\.ex:.*render_ast/,

  # OAuth modules - complex async patterns
  ~r/lib\/mana\/oauth\/.*pattern_match/,

  # Commands session - type confusion from Map operations
  ~r/lib\/mana\/commands\/session\.ex:.*pattern_match/,

  # Models settings - provider matching patterns
  ~r/lib\/mana\/models\/settings\.ex:.*pattern_match_cov/
]
