Output docs/assets/terminal-demo.gif

Set Shell "bash"
Set FontSize 18
Set Width 1200
Set Height 660
Set Theme "Catppuccin Mocha"
Set Padding 28
Set TypingSpeed 28ms
Set PlaybackSpeed 1.25

Hide
Type "demo_dir=$(mktemp -d /tmp/ragproof-demo.XXXXXX) && cd $demo_dir"
Enter
Sleep 500ms
Type "export PS1='› '"
Enter
Type "clear"
Enter
Sleep 500ms
Show

Type "ragproof init ragproof.yaml"
Enter
Sleep 1400ms

Type "ragproof run -c ragproof.yaml -o current.json"
Enter
Sleep 1800ms

Type "ragproof compare --baseline current.json --current current.json --max 'error_rate<=0.0'"
Enter
Sleep 1800ms

Type "ragproof report current.json -o report.html"
Enter
Sleep 2200ms

Hide
Type "cd / && rm -rf $demo_dir"
Enter
