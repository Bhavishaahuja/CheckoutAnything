# Contributing

How Bhavi and Shachi get work into `main`. Nobody pushes to `main` directly.

## Steps

1. **Pick an issue.** Assign yourself. If there's no issue for the work, make one with the Task template first.

2. **Update main and branch off it.**

   ```powershell
   git checkout main
   git pull
   git checkout -b feat/12-mandate-endpoint
   ```

   Branch prefixes: `feat/` new feature, `fix/` bug fix, `spike/` throwaway experiment, `chore/` tooling or deps, `docs/` docs only. Put the issue number in the name.

3. **Commit with conventional messages.**

   ```
   feat: add mandate endpoint
   fix: void authorization when human rejects
   chore: add ruff config
   docs: sandbox login steps
   ```

4. **Run the checks locally before pushing.**

   ```powershell
   ruff check .
   pytest
   ```

   Frontend: `npm run lint` and `npm run build` inside `frontend/`.

5. **Push and open a PR.**

   ```powershell
   git push -u origin feat/12-mandate-endpoint
   gh pr create --fill
   ```

   Fill in the template. The Summary must include `Closes #12` so the issue closes on merge.

6. **Wait for CI to go green.** Fix anything red on the same branch.

7. **Ask the other person to review.** Bhavi reviews Shachi's PRs, Shachi reviews Bhavi's. One approval is required.

8. **Squash and merge**, then delete the branch.

   ```powershell
   git checkout main
   git pull
   git branch -d feat/12-mandate-endpoint
   ```

## Ground rules

- Never commit `.env` or any key. If you do by accident, tell the other person right away and rotate the key.
- Check PayPal's docs (developer.paypal.com, the OpenAPI `schema.yaml` files) before writing any PayPal call. Don't guess shapes.
- Demo store is "Fernwood Supply Co". No real brands.
- No em dashes in docs or UI copy.
