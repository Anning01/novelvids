# Beautiful UI adaptation

AgentDisclosure.vue and AgentActivity.vue adapt the grid disclosure, easing,
chevron rotation and shimmer from Beautiful UI's ThinkingState.tsx and
app/globals.css to Vue and this application's theme tokens.

Sources: https://www.beautifului.dev/#thinking-state
https://github.com/slev12397/beautiful-ui/blob/main/app/globals.css

The original components are React copy-and-paste components. This adaptation
retains the existing Vue chat/editor library. Actual application state drives
loading; the example's simulated trace and timers are not used.

MIT License

Copyright (c) 2026 Shane Levine

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
