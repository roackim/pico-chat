# PRNGs and LCGs

## 1. Introduction to Randomness in Computing

Computers are deterministic machines; given the same input, they always produce the same output. True randomness cannot be generated algorithmically because every operation follows a fixed set of rules. This fundamental limitation led to the development of Pseudorandom Number Generators (PRNGs), which simulate randomness through deterministic processes that appear random to an observer.

## 2. What is a PRNG?

A PRNG is an algorithm that produces a sequence of numbers whose properties approximate those of sequences of truly random numbers. The sequence is not truly random because it is entirely determined by a relatively small set of initial values, called the seed. If the seed is known, the entire sequence can be reproduced.

## 3. Key Properties of Good PRNGs

A high-quality PRNG should exhibit several properties: a long period before the sequence repeats, uniform distribution across its output range, statistical independence between successive values, and unpredictability (at least for non-cryptographic use). The trade-off between speed, quality, and period length defines the suitability of a PRNG for different applications.

## 4. Use Cases for PRNGs

PRNGs are used in simulations, gaming, procedural content generation, Monte Carlo methods, statistical sampling, and randomized algorithms. Cryptographic applications require special cryptographically secure PRNGs (CSPRNGs), which have additional security guarantees that standard PRNGs do not provide.

## 5. Introduction to Linear Congruential Generators

The Linear Congruential Generator (LCG) is one of the oldest and simplest PRNG algorithms, first published in 1948 by George Marsaglia. Despite its age, it remains widely used in embedded systems, educational contexts, and applications where computational resources are limited.

## 6. The LCG Formula

An LCG generates the next number in the sequence using the recurrence relation: `X_{n+1} = (a * X_n + c) mod m`. Here, `X_n` is the current state, `a` is the multiplier, `c` is the increment, and `m` is the modulus. The initial value `X_0` is the seed. Each new value depends linearly on the previous one.

## 7. The Modulus (m)

The modulus determines the range of output values: all generated numbers will fall in `[0, m-1]`. A larger modulus increases the maximum possible period. In practice, `m` is often chosen as a power of two (e.g., `2^32` or `2^64`) because the modulo operation can then be replaced with a bitwise AND or simply by relying on integer overflow.

## 8. The Multiplier (a)

The multiplier is the most critical parameter for determining the quality of an LCG. It controls how the state mixes between iterations. A poorly chosen multiplier can cause the sequence to have a very short period or exhibit obvious patterns. The choice of `a` is constrained by mathematical theorems that govern the maximum achievable period.

## 9. The Increment (c)

The increment adds a constant offset at each step. When `c` is non-zero, the generator is called a mixed LCG. When `c` is zero, it is called a multiplicative congruential generator (MCG). The presence of a non-zero increment relaxes the constraints on `a` for achieving a full period, making mixed LCGs easier to parameterize correctly.

## 10. The Seed (X_0)

The seed initializes the generator's state. Changing the seed produces a different sequence. The seed must be in the range `[0, m-1]`. If the same seed is used, the LCG will produce the exact same sequence, which is useful for reproducibility in simulations and debugging.

## 11. The Hull-Dobell Theorem

The Hull-Dobell Theorem provides necessary and sufficient conditions for an LCG to achieve its maximum possible period of `m`. The conditions are: (1) `c` and `m` are coprime, (2) every prime factor of `m` divides `a - 1`, and (3) if `m` is divisible by 4, then `a - 1` is also divisible by 4. When these hold, every value in `[0, m-1]` appears exactly once per period.

## 12. Period Length

The period is the number of values generated before the sequence repeats. For an LCG, the maximum period is `m`. In practice, achieving the full period requires careful parameter selection. A short period means the sequence will repeat quickly, which is undesirable for most applications.

## 13. Spectral Test and Lattice Structure

LCGs suffer from a fundamental structural weakness: successive values, when plotted in higher-dimensional space, fall on a small number of hyperplanes. This is known as the lattice structure of LCGs. The spectral test measures the quality of this structure by finding the closest distance between hyperplanes. A larger distance indicates better quality.

## 14. The Birthday Paradox Problem

When an LCG is used to generate pairs of values, correlations emerge that would not exist in truly random sequences. This is sometimes called the "birthday space" problem. In Monte Carlo simulations, this can cause systematic bias, making LCGs unsuitable for certain statistical applications.

## 15. Known LCG Implementations

Several LCGs are well-known in practice. The glibc LCG uses `a=1103515245, c=12345, m=2^31`. The MINSTD generator uses `a=16807, c=0, m=2^31 - 1`. The Numerical Recipes LCG uses `a=1664525, c=1013904223, m=2^32`. Each has different trade-offs in period, quality, and speed.

## 16. Strengths of LCGs

LCGs are extremely fast and have minimal memory requirements (only the current state is needed). They are easy to implement and understand, making them suitable for embedded systems, real-time applications, and educational purposes. When `m` is a power of two, the modulo operation is essentially free due to integer overflow or bitwise masking.

## 17. Weaknesses of LCGs

LCGs have poor statistical properties in higher dimensions, short periods relative to modern generators, and predictable sequences. The low-order bits of LCG output have significantly shorter periods than the high-order bits, so only the most significant bits should be used. They are also trivial to reverse-engineer, making them unsuitable for cryptography.

## 18. Modern Alternatives

Modern PRNGs such as the Mersenne Twister, PCG (Permuted Congruential Generator), Xorshift, and ChaCha20-based generators offer vastly superior statistical properties and period lengths. The PCG family, in particular, builds on the LCG structure but applies a permutation step to the output, masking the lattice structure while retaining speed.

## 19. The PCG Improvement

The PCG generator uses an LCG internally for state transition but applies a non-linear output function that destroys the lattice structure. This combines the speed and simplicity of LCGs with the statistical quality of more complex generators. PCG is recommended for general-purpose use where cryptographic security is not required.

## 20. Summary and Recommendations

LCGs are historically important and pedagogically useful but should generally be avoided in production software where statistical quality matters. For simple use cases, consider PCG or Xorshift variants. For simulations requiring high-dimensional randomness, use a generator with a proven spectral test performance. For cryptographic purposes, always use a CSPRNG provided by your operating system or a well-vetted library.
