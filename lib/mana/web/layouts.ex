defmodule Mana.Web.Layouts do
  @moduledoc """
  Root layout component for the Mana web interface.

  Provides the HTML page structure including:
  - Meta tags and viewport settings
  - Title and base styles
  - Asset references (CSS/JS)
  - Inner content placeholder

  The root layout wraps all LiveViews and serves as the
  outer HTML document structure.

  """

  use Phoenix.Component

  @doc """
  Root layout for the Mana web application.

  Provides the HTML document structure with:
  - UTF-8 charset and viewport meta tags
  - Page title set to "Mana"
  - Static asset links for CSS and JavaScript
  - Inner content injection point

  """
  def root(assigns) do
    ~H"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Mana</title>
        <link phx-track-static rel="stylesheet" href="/assets/app.css" />
        <script defer phx-track-static type="text/javascript" src="/assets/app.js"></script>
      </head>
      <body>
        <%= @inner_content %>
      </body>
    </html>
    """
  end
end
