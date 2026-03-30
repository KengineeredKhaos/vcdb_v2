Absolutely — here’s a compact cross-language cheat sheet for:

- **Bash / shell**

- **JSON**

- **Python**

- **Jinja**

The biggest source of confusion is that the **same symbols mean different things** in each one.

# Quick symbol map

## Parentheses `( )`

**Bash**

- Run commands in a **subshell**

```bash
(cd /tmp && ls)
```

**JSON**

- **Not used** for structure

**Python**

- Group expressions, call functions, define tuples

```python
print("hello")
x = (1 + 2) * 3
t = (1, 2)
```

**Jinja**

- Group expressions, call filters/functions inside template logic

```jinja
{% if (count + 1) > 3 %}
```

---

## Square brackets `[ ]`

**Bash**

- Test command

```bash
[ -f "file.txt" ]
```

- `[[ ... ]]` is the bash-native test form

**JSON**

- Array / list

```json
["a", "b", "c"]
```

**Python**

- List, indexing, slicing

```python
items = [1, 2, 3]
name = items[0]
```

**Jinja**

- List literals, indexing

```jinja
{{ items[0] }}
{% set nums = [1, 2, 3] %}
```

---

## Curly braces `{ }`

**Bash**

- Group commands in current shell

```bash
{ echo one; echo two; }
```

- Brace expansion

```bash
echo file_{a,b}.txt
```

- Variable boundary

```bash
echo "${HOME}/file.txt"
```

**JSON**

- Object / dictionary

```json
{ "name": "Shaw", "active": true }
```

**Python**

- Dict, set, f-strings

```python
d = {"name": "Shaw"}
s = {1, 2, 3}
f"{name}"
```

**Jinja**

- **Single braces alone are usually just literal characters**

- Jinja syntax uses:
  
  - `{{ ... }}` = print output
  
  - `{% ... %}` = logic / control flow
  
  - `{# ... #}` = comment

Examples:

```jinja
{{ user.name }}
{% if user %}
  Hello
{% endif %}
{# hidden comment #}
```

**Important Jinja rule:**

- **Use `{{ ... }}` when you want to print something**

- **Use `{% ... %}` when you want to do something**

- **Use `{# ... #}` when you want to comment something out**

- **Single `{` or `}` by themselves are not normal Jinja syntax**

---

# Quotes

## Single quotes `' '`

**Bash**

- Literal text, no variable expansion

```bash
echo '$HOME'
```

**JSON**

- **Not valid for strings**

- JSON strings must use **double quotes**

```json
{ "name": "Shaw" }
```

**Python**

- Valid string delimiter

```python
name = 'Shaw'
```

**Jinja**

- Valid string delimiter inside expressions

```jinja
{{ user.get('name', 'unknown') }}
{% if role == 'admin' %}
```

---

## Double quotes `" "`

**Bash**

- Protect spaces, but still allow `$var` expansion

```bash
echo "Home is $HOME"
```

**JSON**

- Required for strings and object keys

```json
{ "title": "Example" }
```

**Python**

- Valid string delimiter

```python
name = "Shaw"
```

**Jinja**

- Valid string delimiter inside expressions

```jinja
{% if role == "admin" %}
```

---

# Backslash `\`

**Bash**

- Escape the next character

```bash
mkdir My\ Folder
echo \$HOME
```

**JSON**

- Escape inside strings

```json
{ "path": "C:\\temp\\file.txt" }
```

**Python**

- Escape inside strings unless using raw strings

```python
path = "C:\\temp\\file.txt"
raw = r"C:\temp\file.txt"
```

**Jinja**

- Usually just part of a string literal if you are writing one

- Not a primary template syntax tool the way it is in Bash

---

# Colon `:`

**Bash**

- Rarely meaningful in normal commands

**JSON**

- Key/value separator

```json
{ "name": "Shaw" }
```

**Python**

- Block starter, dict separator, slice syntax

```python
if ok:
    print("yes")

d = {"name": "Shaw"}
items[1:3]
```

**Jinja**

- Not special on its own in most template syntax, except inside Python-like expressions or dict literals

---

# Comma `,`

**Bash**

- Usually just a normal character unless used in brace expansion

**JSON**

- Separates items

```json
["a", "b", "c"]
```

**Python**

- Separates items, arguments, tuple elements

```python
x = 1, 2
print("a", "b")
```

**Jinja**

- Same general role inside expressions

```jinja
{{ func(a, b) }}
{% set d = {"a": 1, "b": 2} %}
```

---

# Equal sign `=`

**Bash**

- Variable assignment, no spaces

```bash
NAME="Shaw"
```

**JSON**

- **Not used** for key/value pairs

**Python**

- Assignment

```python
name = "Shaw"
```

**Jinja**

- Used in `{% set %}` assignments

```jinja
{% set name = "Shaw" %}
```

- In comparisons, use `==`, not `=`

---

# The Jinja part that trips people most

## `{{ ... }}`

Use this to **print** something into the HTML.

Example:

```jinja
<p>{{ user_name }}</p>
```

If `user_name = "Shaw"`, output becomes:

```html
<p>Shaw</p>
```

---

## `{% ... %}`

Use this for **logic**, not direct printing.

Examples:

```jinja
{% if user_name %}
  <p>Hello {{ user_name }}</p>
{% endif %}
```

```jinja
{% for item in items %}
  <li>{{ item }}</li>
{% endfor %}
```

---

## `{# ... #}`

Use this for **template comments**.

```jinja
{# This will not render in HTML output #}
```

---

## Single braces in Jinja

Single braces like this:

```jinja
{ user_name }
```

are usually just plain text, not Jinja output.

If you want to print a variable, it must be:

```jinja
{{ user_name }}
```

That is the rule to remember.

---

# Fast “when do I use what?” guide

## Bash

Use:

- quotes to protect spaces and special characters

- `\` to escape one character

- `[]` or `[[ ]]` for tests

- `{}` for grouping or brace expansion

- `()` for subshells

## JSON

Use:

- `{}` for objects

- `[]` for arrays

- `:` for key/value

- `"` double quotes only

- no comments, no trailing commas

## Python

Use:

- `()` for calls/grouping/tuples

- `[]` for lists/indexing

- `{}` for dicts/sets

- either `' '` or `" "` for strings

## Jinja

Use:

- `{{ ... }}` to print

- `{% ... %}` for logic

- `{# ... #}` for comments

- `' '` or `" "` for strings inside expressions

---

# A few side-by-side examples

## A list

**JSON**

```json
["a", "b", "c"]
```

**Python**

```python
items = ["a", "b", "c"]
```

**Jinja**

```jinja
{% set items = ["a", "b", "c"] %}
{{ items[0] }}
```

---

## An object / dict

**JSON**

```json
{ "name": "Shaw", "active": true }
```

**Python**

```python
user = {"name": "Shaw", "active": True}
```

**Jinja**

```jinja
{{ user["name"] }}
{{ user.name }}
```

---

## A conditional

**Bash**

```bash
if [ -f "file.txt" ]; then
  echo "exists"
fi
```

**Python**

```python
if file_exists:
    print("exists")
```

**Jinja**

```jinja
{% if file_exists %}
  exists
{% endif %}
```

---

# The shortest memory aid

- **Bash**: symbols control the shell

- **JSON**: symbols describe data only

- **Python**: symbols build code and data

- **Jinja**: symbols mix template logic with output

And the key Jinja rule:

- `{{ ... }}` = **show it**

- `{% ... %}` = **do it**

- `{# ... #}` = **hide it**

If you want, I can turn this into a clean **VCDB Snippets** formatted block you can drop straight into your notes.
