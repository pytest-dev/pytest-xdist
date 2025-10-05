import java.util.Stack;

/**
 * This class converts an infix expression (e.g. A+B*C)
 * into a postfix expression (e.g. A B C * +)
 * using the Stack data structure.
 *
 * Time Complexity: O(n)
 * Space Complexity: O(n)
 */
public class InfixToPostfix {

    private static boolean isOperand(char c) {
        return Character.isLetterOrDigit(c);
    }

    private static int precedence(char op) {
        switch (op) {
            case '^': return 3;
            case '*': case '/': return 2;
            case '+': case '-': return 1;
            default: return -1;
        }
    }

    public static String convert(String exp) {
        StringBuilder result = new StringBuilder();
        Stack<Character> stack = new Stack<>();

        for (int i = 0; i < exp.length(); i++) {
            char c = exp.charAt(i);

            // Operand → add to result
            if (isOperand(c)) {
                result.append(c);
            }
            // Opening parenthesis
            else if (c == '(') {
                stack.push(c);
            }
            // Closing parenthesis
            else if (c == ')') {
                while (!stack.isEmpty() && stack.peek() != '(') {
                    result.append(stack.pop());
                }
                if (!stack.isEmpty() && stack.peek() == '(') {
                    stack.pop();
                }
            }
            // Operator
            else {
                while (!stack.isEmpty() && precedence(stack.peek()) >= precedence(c)) {
                    result.append(stack.pop());
                }
                stack.push(c);
            }
        }

        // Pop remaining operators
        while (!stack.isEmpty()) {
            result.append(stack.pop());
        }

        return result.toString();
    }

    public static void main(String[] args) {
        String exp = "A+B*C";
        System.out.println("Infix: " + exp);
        System.out.println("Postfix: " + convert(exp));
    }
}
