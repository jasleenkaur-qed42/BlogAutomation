---
title: An overview of design tokens and why they matter
slug: design-tokens-overview
description: An overview of design tokens, the design system basics and CSS variables, and why small front-end teams should consider using them for consistency.
keywords: [design tokens, design system, css variables]
claims: []
---
# An overview of design tokens and why they matter

Design tokens are an important concept in modern design systems. In this article we will discuss design tokens and why design tokens matter for design teams and development teams of every size.

## Overview
Design tokens are named entities that store visual design attributes. They are used in place of hard-coded values in order to maintain a scalable and consistent visual system. Design tokens can represent colors, typography, spacing and other values, and they are a foundational building block of a design system.

## Benefits
Design tokens are a useful idea for teams that care about consistency. They give designers and developers a shared vocabulary for visual decisions.

## Usage
Design tokens can be used in CSS, in JavaScript and in native applications. Teams can store design tokens in JSON files and transform them into the formats that each platform needs. CSS variables are one common way to use design tokens on the web.

## Types of tokens
There are many types of design tokens, including color tokens, spacing tokens, typography tokens and others. Each type of token represents a different design attribute and helps teams keep their products consistent.

## Frequently asked questions
### How do I migrate a codebase that already has hard-coded values?
Search for each hex value to see how often it repeats, and tokenize the most repeated ones first. For near-duplicates, such as three similar greens, ask a designer which one is intended before you merge them.

### How do I keep a dark theme readable when I override tokens?
Check every text and background pair against the WCAG minimum contrast ratio of 4.5:1 for body text. Overriding a surface token can break text that was readable on the light theme.

### How do I decide between a token and a one-off value?
Ask whether the value will appear again or change with a theme. If neither is true, keep it inline.

### When should I move from CSS variables to a token build step?
When you ship to more than the web, or when designers export values from a design tool as JSON. Until then, one CSS file is easier to review and needs no tooling.

### How do I catch typos in CSS variable names?
Use a visual regression test, because a `var()` that points at an undefined property makes the declaration invalid at computed-value time and the browser falls back to the inherited or initial value.

## Conclusion
Design tokens are an important part of design systems. Teams of any size should consider using design tokens.

## References
- [Using CSS custom properties (MDN)](https://developer.mozilla.org/en-US/docs/Web/CSS/Using_CSS_custom_properties)
- [W3C Design Tokens Community Group](https://www.w3.org/community/design-tokens/)
- [Contrast (minimum), WCAG 2.2](https://www.w3.org/TR/WCAG22/#contrast-minimum)
