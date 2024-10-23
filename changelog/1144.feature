The internal `steal` command is now atomic - it unschedules either all requested tests or none.

This is a prerequisite for group/scope support in the `worksteal` scheduler, so test groups won't be broken up incorrectly.
