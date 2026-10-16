Output docs/demo.gif
Set Shell "bash"
Set FontSize 18
Set Width 1400
Set Height 620
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms

Hide
Type "source .venv/bin/activate && export PS1='$ ' && clear"
Enter
Show

Type "# The agent refunded $4,999 for a $49.99 laptop. Which prompt fixes it?"
Enter
Sleep 1s
Type `agentfork sweep de994fe6 --step 3 --repeat 2 --expect "49.99" --system "You are a support agent. Look up the order, then refund the full order amount in USD." --system "You are a support agent. Look up the order, then refund the full order amount in USD. Order amounts from the API are in cents; divide by 100 before refunding."`
Enter
Sleep 14s
