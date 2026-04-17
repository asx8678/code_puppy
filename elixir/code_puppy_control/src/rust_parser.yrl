%%-----------------------------------------------------------------------------
%% @doc Rust Parser for CodePuppyControl
%%
%% This is a Yecc-generated parser for Rust source code.
%% It extracts top-level declarations including:
%%
%%   - Functions (fn)
%%   - Structs (struct)
%%   - Enums (enum)
%%   - Impl blocks (impl)
%%   - Traits (trait)
%%   - Modules (mod)
%%   - Use statements (use)
%%   - Type aliases (type)
%%   - Constants (const)
%%   - Static items (static)
%%
%% The grammar is intentionally simple and focused on extracting
%% symbols for code navigation, not full compilation.
%%
%% Generated module: :rust_parser
%%-----------------------------------------------------------------------------

Nonterminals
  program items item
  fn_decl struct_decl enum_decl impl_block trait_decl mod_decl use_stmt
  type_decl const_decl static_decl
  visibility
  parameters parameter
  type_params type_param_list
  where_clause
  newlines
  .

Terminals
  fn pub struct enum impl trait mod use const static type where
  identifier
  '(' ')' '{' '}' '[' ']' ',' ';' ':' assign '<' '>' path_sep
  '->' '=>' '::' '+' '-' '*' '/' '&' '|' '!' '#' '$' '?' '.'
  plus_assign minus_assign mult_assign div_assign
  eq ne le ge and_op or_op
  string raw_string char integer float
  lifetime
  newline let mut ref move async await unsafe extern crate
  self self_capital super as true_token false_token
  for if else match while loop break_token continue_token return
  lshift rshift lshift_assign rshift_assign
  bitand bitor bitxor bitand_assign bitor_assign bitxor_assign
  .

Rootsymbol program.

%%---------------------------------------------------------------------------
%% Program Structure
%%---------------------------------------------------------------------------

program -> '$empty' : [].
program -> items : '$1'.
program -> newlines items : '$2'.
program -> newlines : [].

items -> item : ['$1'].
items -> item newlines : ['$1'].
items -> item newlines items : ['$1' | '$3'].

newlines -> newline : skip.
newlines -> newline newlines : skip.

%%---------------------------------------------------------------------------
%% Items (Top-level Declarations)
%%---------------------------------------------------------------------------

item -> fn_decl : '$1'.
item -> struct_decl : '$1'.
item -> enum_decl : '$1'.
item -> impl_block : '$1'.
item -> trait_decl : '$1'.
item -> mod_decl : '$1'.
item -> use_stmt : '$1'.
item -> type_decl : '$1'.
item -> const_decl : '$1'.
item -> static_decl : '$1'.

%%---------------------------------------------------------------------------
%% Visibility Modifiers
%%---------------------------------------------------------------------------

visibility -> '$empty' : [].
visibility -> pub : [pub].

%%---------------------------------------------------------------------------
%% Function Declarations
%%---------------------------------------------------------------------------

fn_decl -> fn identifier '(' ')' '{' '}' :
    {function, line('$1'), unwrap('$2'), [], []}.
fn_decl -> fn identifier '(' ')' '->' identifier '{' '}' :
    {function, line('$1'), unwrap('$2'), [], [{return_type, unwrap('$6')}]}.
fn_decl -> fn identifier '(' parameters ')' '{' '}' :
    {function, line('$1'), unwrap('$2'), '$4', []}.
fn_decl -> visibility fn identifier '(' ')' '{' '}' :
    {function, line('$2'), unwrap('$3'), [], '$1'}.
fn_decl -> visibility fn identifier '(' parameters ')' '{' '}' :
    {function, line('$2'), unwrap('$3'), '$5', '$1'}.

%%---------------------------------------------------------------------------
%% Struct Declarations
%%---------------------------------------------------------------------------

struct_decl -> struct identifier '{' '}' :
    {struct, line('$1'), unwrap('$2'), []}.
struct_decl -> visibility struct identifier '{' '}' :
    {struct, line('$2'), unwrap('$3'), '$1'}.

%%---------------------------------------------------------------------------
%% Enum Declarations
%%---------------------------------------------------------------------------

enum_decl -> enum identifier '{' '}' :
    {enum, line('$1'), unwrap('$2'), []}.
enum_decl -> visibility enum identifier '{' '}' :
    {enum, line('$2'), unwrap('$3'), '$1'}.

%%---------------------------------------------------------------------------
%% Impl Blocks
%%---------------------------------------------------------------------------

impl_block -> impl identifier '{' '}' :
    {impl, line('$1'), unwrap('$2'), nil, []}.
impl_block -> impl identifier for identifier '{' '}' :
    {impl, line('$1'), unwrap('$4'), unwrap('$2'), []}.

%%---------------------------------------------------------------------------
%% Trait Declarations
%%---------------------------------------------------------------------------

trait_decl -> trait identifier '{' '}' :
    {trait, line('$1'), unwrap('$2'), []}.
trait_decl -> visibility trait identifier '{' '}' :
    {trait, line('$2'), unwrap('$3'), '$1'}.

%%---------------------------------------------------------------------------
%% Module Declarations
%%---------------------------------------------------------------------------

mod_decl -> mod identifier '{' '}' :
    {mod, line('$1'), unwrap('$2'), block, []}.
mod_decl -> mod identifier ';' :
    {mod_file, line('$1'), unwrap('$2'), []}.
mod_decl -> visibility mod identifier '{' '}' :
    {mod, line('$2'), unwrap('$3'), block, '$1'}.
mod_decl -> visibility mod identifier ';' :
    {mod_file, line('$2'), unwrap('$3'), '$1'}.

%%---------------------------------------------------------------------------
%% Use Statements
%%---------------------------------------------------------------------------

use_stmt -> use identifier ';' :
    {use, line('$1'), unwrap('$2'), simple}.
use_stmt -> use identifier path_sep identifier ';' :
    {use, line('$1'), {unwrap('$2'), unwrap('$4')}, path}.

%%---------------------------------------------------------------------------
%% Type Declarations
%%---------------------------------------------------------------------------

type_decl -> type identifier assign identifier ';' :
    {type_alias, line('$1'), unwrap('$2'), unwrap('$4'), []}.
type_decl -> visibility type identifier assign identifier ';' :
    {type_alias, line('$2'), unwrap('$3'), unwrap('$5'), '$1'}.

%%---------------------------------------------------------------------------
%% Constant Declarations
%%---------------------------------------------------------------------------

const_decl -> const identifier assign integer ';' :
    {const, line('$1'), unwrap('$2'), unwrap('$4'), []}.
const_decl -> visibility const identifier assign integer ';' :
    {const, line('$2'), unwrap('$3'), unwrap('$5'), '$1'}.

%%---------------------------------------------------------------------------
%% Static Declarations
%%---------------------------------------------------------------------------

static_decl -> static identifier assign integer ';' :
    {static, line('$1'), unwrap('$2'), unwrap('$4'), []}.
static_decl -> static mut identifier assign integer ';' :
    {static, line('$1'), unwrap('$3'), unwrap('$5'), [mut]}.
static_decl -> visibility static identifier assign integer ';' :
    {static, line('$2'), unwrap('$3'), unwrap('$5'), '$1'}.

%%---------------------------------------------------------------------------
%% Parameters (for functions)
%%---------------------------------------------------------------------------

parameters -> parameter : ['$1'].
parameters -> parameter ',' parameters : ['$1' | '$3'].

parameter -> identifier ':' identifier :
    {unwrap('$1'), unwrap('$3')}.
parameter -> identifier :
    unwrap('$1').

%%---------------------------------------------------------------------------
%% Utility Functions
%%---------------------------------------------------------------------------

Erlang code.

%% @doc Extract line number from token
line({_, Line}) -> Line;
line({_, Line, _}) -> Line.

%% @doc Extract value from token
unwrap({_, _, V}) -> V;
unwrap({_, V}) -> V.
