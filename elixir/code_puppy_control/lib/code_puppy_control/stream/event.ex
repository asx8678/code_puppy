defmodule CodePuppyControl.Stream.Event do
  @moduledoc "Stream event types for agent loop callbacks."

  defmodule TextDelta do
    @moduledoc false
    defstruct [:text]
  end

  defmodule ToolCallEnd do
    @moduledoc false
    defstruct [:name, :arguments, :id]
  end

  defmodule Done do
    @moduledoc false
    defstruct []
  end
end
