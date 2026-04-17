Nonterminals
  program statements statement simple_stmt
  function_def class_def import_stmt
  parameters parameter
  decorator decorators suite
  .

Terminals
  def class import from as pass return identifier
  '(' ')' ':' ',' '@' newline
  .

Rootsymbol program.

% Handle empty input (returns empty AST)
program -> '$empty' : [].
program -> statements : '$1'.

statements -> statement : ['$1'].
statements -> statement statements : ['$1' | '$2'].

statement -> function_def : '$1'.
statement -> class_def : '$1'.
statement -> import_stmt : '$1'.
statement -> decorators function_def : add_decorators('$1', '$2').
statement -> decorators class_def : add_decorators('$1', '$2').
statement -> simple_stmt : '$1'.
statement -> newline : skip.

% Simple statements (pass, return, etc.) - we extract these but don't build full AST
simple_stmt -> pass : skip.
simple_stmt -> return : skip.
simple_stmt -> return identifier : skip.

function_def -> def identifier '(' parameters ')' ':' :
    {function, line('$1'), unwrap('$2'), '$4'}.
function_def -> def identifier '(' ')' ':' :
    {function, line('$1'), unwrap('$2'), []}.

% Class definitions with consistent format (always include params list)
class_def -> class identifier ':' :
    {class, line('$1'), unwrap('$2'), []}.
class_def -> class identifier '(' ')' ':' :
    {class, line('$1'), unwrap('$2'), []}.
class_def -> class identifier '(' parameters ')' ':' :
    {class, line('$1'), unwrap('$2'), '$4'}.

import_stmt -> import identifier : {import, line('$1'), unwrap('$2')}.
import_stmt -> from identifier import identifier : {from_import, line('$1'), unwrap('$2'), unwrap('$4')}.

decorators -> decorator : ['$1'].
decorators -> decorator decorators : ['$1' | '$2'].

decorator -> '@' identifier newline : {decorator, line('$1'), unwrap('$2')}.

parameters -> parameter : ['$1'].
parameters -> parameter ',' parameters : ['$1' | '$3'].

parameter -> identifier : unwrap('$1').

Erlang code.

line({_, Line}) -> Line;
line({_, Line, _}) -> Line.

unwrap({_, _, V}) -> V;
unwrap({_, V}) -> V.

% Add decorators to class/function AST nodes
% Always produces a 5-tuple: {Type, Line, Name, Params, Decorators}
% For simple classes/functions, Params=[]
add_decorators(Decorators, {Type, Line, Name, Params}) -> {Type, Line, Name, Params, Decorators};
% Handle 3-tuple format (no params) by adding empty params list
add_decorators(Decorators, {Type, Line, Name}) -> {Type, Line, Name, [], Decorators}.
