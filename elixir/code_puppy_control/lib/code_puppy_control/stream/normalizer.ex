defmodule CodePuppyControl.Stream.Normalizer do
  @moduledoc "Normalizes raw stream callbacks into a standard shape."

  @spec normalize(fun()) :: fun()
  def normalize(callback) when is_function(callback, 1), do: callback
end
