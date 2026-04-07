# Test fixture: with_imports.ex
# Purpose: Test import, use, require, alias statements
# Expected symbols: 1 module (WithImports), multiple import/use/require/alias statements

defmodule WithImports do
  @moduledoc """
  Module demonstrating various import mechanisms in Elixir.
  Tests that the parser handles these statements correctly.
  """

  # Alias - creates an alias for a module
  alias MyApp.User
  alias MyApp.Accounts, as: AccountsModule

  # Import - imports functions from another module
  import List, only: [flatten: 1, foldl: 3]
  import Enum, except: [map: 2]

  # Require - needed to use macros from other modules
  require Logger
  require Integer

  # Use - invokes the __using__ macro of a module
  use GenServer
  use Ecto.Schema

  def demo do
    # Using imported functions
    flatten([[1, 2], [3, 4]])
  end
end
