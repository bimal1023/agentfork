Output docs/demo.gif
Set FontSize 14
Set Width 1500
Set Height 850
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms

Hide
Type "source .venv/bin/activate && clear"
Enter
Show

Type "# Our refund agent paid $4,999 for a $49.99 laptop. Better model or better prompt?"
Enter
Sleep 1s
Type `agentfork sweep de994fe6 --step 3 --repeat 2 --expect "49.99" --model gpt-4o-mini,gpt-4o`
Enter
Sleep 14s
Type `agentfork sweep de994fe6 --step 3 --repeat 2 --expect "49.99" --system "You are a support agent. Look up the order, then refund the full order amount in USD." --system "You are a support agent. Look up the order, then refund the full order amount in USD. Order amounts from the API are in cents; divide by 100 before refunding."`
Enter
Sleep 14s
