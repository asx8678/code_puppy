# Dialyzer ignore patterns for Mana project
# Only upstream/stdlib issues and dialyzer limitations are suppressed here.
# All fixable issues in our code should be fixed rather than suppressed.

[
  # Mix module - Mix is a build tool, not available in runtime PLT
  # These are upstream Elixir issues (Mix module functions not in PLT)
  ~r/unknown_function.*Mix\.(shell|Task)/,
  ~r/callback_info_missing.*Mix\.Task/,

  # DynamicSupervisor type - stdlib type should be in PLT but sometimes isn't found
  ~r/unknown_type.*DynamicSupervisor\.on_start/,

  # MapSet opaque type mismatch - dialyzer limitation with ETS constructed MapSets
  # The MapSet is built from ETS select results, which dialyzer tracks as raw Erlang :set
  ~r/lib\/mana\/tools\/registry\.ex:.*call_without_opaque/
]
