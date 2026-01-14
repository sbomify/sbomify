import globals from "globals";
import js from "@eslint/js";
import typescript from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";

export default [
  {
    ignores: [
      "static/**/*.js",
      "staticfiles/**/*.js",
      "**/node_modules/**",
      "**/dist/**",
      "**/build/**",
      "**/*.min.js"
    ],
  },
  {
    files: ["**/*.{js,mjs,cjs,jsx,mjsx,ts,tsx,mtsx}"],
    ...js.configs.recommended,
    languageOptions: {
      globals: {
        ...globals.browser,
      },
      parser: tsParser,
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
      },
    },
    plugins: {
      "@typescript-eslint": typescript,
    },
    rules: {
      ...typescript.configs["eslint-recommended"].rules,
      ...typescript.configs.recommended.rules,
    },
  },
];