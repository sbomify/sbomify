import { parse } from 'license-expressions';

export interface LicenseInfo {
    key: string;
    name: string;
    category?: string | null;
    origin?: string;
}

export type TokenType = 'IDENTIFIER' | 'PAREN' | 'UNKNOWN';

// Maximum number of license suggestions to return
const MAX_LICENSE_SUGGESTIONS = 20;

export interface Token {
    type: TokenType;
    value: string;
    start: number;
    end: number;
}

/**
 * Tokenizes a license expression into a list of tokens.
 * Handles identifiers (licenses, operators), parentheses, and whitespace.
 */
export function tokenize(expression: string): Token[] {
    const tokens: Token[] = [];
    let current = 0;

    while (current < expression.length) {
        let char = expression[current];

        // Skip whitespace
        if (/\s/.test(char)) {
            current++;
            continue;
        }

        // Handle parentheses
        if (char === '(' || char === ')') {
            tokens.push({
                type: 'PAREN',
                value: char,
                start: current,
                end: current + 1
            });
            current++;
            continue;
        }

        // Handle identifiers (licenses, operators)
        // Allowed chars in SPDX license IDs: alphanumeric, dot, dash, plus
        // Note: We stop at whitespace, unlike the library which might allow spaces in IDs.
        if (/[a-zA-Z0-9.\-+]/.test(char)) {
            let value = '';
            const start = current;
            while (current < expression.length && /[a-zA-Z0-9.\-+]/.test(expression[current])) {
                value += expression[current];
                current++;
            }
            tokens.push({
                type: 'IDENTIFIER',
                value: value,
                start: start,
                end: current
            });
            continue;
        }

        // Unknown character
        tokens.push({
            type: 'UNKNOWN',
            value: char,
            start: current,
            end: current + 1
        });
        current++;
    }

    return tokens;
}

/**
 * Returns filtered licenses based on the current expression state.
 * Uses a hybrid strategy:
 * 1. Try to parse with 'license-expressions' library to handle valid complex expressions.
 * 2. Fallback to robust tokenization for partial/incomplete inputs.
 * 
 * Note: Both frontend and backend use the license-expressions library
 * (license-expressions for TypeScript/JavaScript, license_expression for Python)
 * for parsing and detecting license expressions, ensuring consistent behavior
 * across the application stack.
 */
export function getFilteredLicenses(expression: string, licenses: LicenseInfo[]): LicenseInfo[] {
    const operators = ['AND', 'OR', 'WITH'];
    let searchTerm = '';
    let expectingOperator = false;
    let forceFallback = false;

    // Strategy 1: Library Parsing (for valid expressions)
    try {
        const ast = parse(expression);

        // Helper to get right-most leaf
        // The parse function returns an AST node with various properties
        interface LicenseASTNode {
            right?: LicenseASTNode;
            exception?: string;
            license?: string;
            [key: string]: unknown;
        }
        const getRightMostValue = (node: LicenseASTNode): string => {
            if (node.right) return getRightMostValue(node.right);
            if (node.exception) return node.exception; // For WITH clauses
            if (node.license) return node.license;
            return '';
        };

        const lastVal = getRightMostValue(ast as LicenseASTNode);

        // Heuristic: If the parsed license identifier contains a space, 
        // it means the parser greedily consumed what might be an operator (e.g. "Apache-2.0 WI").
        // Since strict SPDX IDs don't have spaces, we fallback to our tokenizer to check for split tokens.
        if (lastVal && lastVal.includes(' ')) {
            throw new Error('Likely partial operator consumed as ID');
        }

        // Check for trailing whitespace which indicates we are moving to next token
        if (expression.trim() !== expression && expression.length > 0) {
            expectingOperator = true;
            searchTerm = '';
        } else {
            if (lastVal) {
                searchTerm = lastVal;
                expectingOperator = false;
            }
        }
    } catch {
        // Library parsing failed (incomplete/invalid expression), use tokenizer fallback
        forceFallback = true;
    }

    if (forceFallback) {
        // Strategy 2: Tokenizer Fallback (for partial expressions)
        const tokens = tokenize(expression);

        if (tokens.length === 0 && !expression.trim()) {
            return licenses.slice(0, MAX_LICENSE_SUGGESTIONS);
        }

        const lastToken = tokens[tokens.length - 1];
        const hasTrailingWhitespace = expression.length > (lastToken ? lastToken.end : 0);

        if (!lastToken) {
            searchTerm = '';
        } else if (hasTrailingWhitespace) {
            // Finished a token, typed space
            if (lastToken.type === 'IDENTIFIER') {
                if (operators.includes(lastToken.value.toUpperCase())) {
                    // "AND " -> Expecting License
                    expectingOperator = false;
                } else {
                    // "Apache-2.0 " -> Expecting Operator
                    expectingOperator = true;
                }
            } else if (lastToken.value === ')') {
                // ") " -> Expecting Operator
                expectingOperator = true;
            } else {
                // "( " -> Expecting License
                expectingOperator = false;
            }
        } else {
            // Typing a token
            if (lastToken.type === 'IDENTIFIER') {
                const prevToken = tokens[tokens.length - 2];
                if (prevToken) {
                    if (prevToken.type === 'IDENTIFIER') {
                        // Check if prevToken is an Operator
                        if (!operators.includes(prevToken.value.toUpperCase())) {
                            // Prev was License -> Expecting Operator
                            expectingOperator = true;
                        } else {
                            // Prev was Operator -> Expecting License
                            expectingOperator = false;
                        }
                    } else if (prevToken.value === ')') {
                        expectingOperator = true;
                    }
                } else {
                    expectingOperator = false;
                }
                searchTerm = lastToken.value;
            } else {
                searchTerm = '';
            }
        }
    }

    searchTerm = searchTerm.toLowerCase();

    // Prepare suggestions
    const suggestions: LicenseInfo[] = [];

    if (expectingOperator) {
        operators.forEach(op => {
            if (op.toLowerCase().startsWith(searchTerm)) {
                suggestions.push({
                    key: op,
                    name: `${op} operator`,
                    category: 'operator'
                });
            }
        });
    }

    if (!expectingOperator) {
        const licenseMatches = licenses.filter(item => {
            const k = item.key.toLowerCase();
            const n = item.name.toLowerCase();
            return k.includes(searchTerm) || n.includes(searchTerm);
        });
        suggestions.push(...licenseMatches);
    }

    return suggestions.slice(0, MAX_LICENSE_SUGGESTIONS);
}
