# NightPaw Legal Docs

These files are developer-prepared templates based on the current NightPaw codebase. They are not legal advice and do not guarantee Discord app verification.

## Files

- [Terms of Service](./terms-of-service.md)
- [Privacy Policy](./privacy-policy.md)

## Publish With GitHub Pages

One simple approach is to publish the repository's `docs` folder with GitHub Pages.

1. Push the `docs/` folder to your default branch.
2. In GitHub, open the repository.
3. Go to `Settings` -> `Pages`.
4. Under `Build and deployment`, choose `Deploy from a branch`.
5. Select your default branch.
6. Select the `/docs` folder.
7. Save and wait for Pages to finish deploying.

After deployment, GitHub Pages will give you a site base URL such as:

`https://YOUR-USERNAME.github.io/YOUR-REPO/`

Your legal document URLs will then usually be under that base, for example:

- `https://YOUR-USERNAME.github.io/YOUR-REPO/legal/terms-of-service.html`
- `https://YOUR-USERNAME.github.io/YOUR-REPO/legal/privacy-policy.html`

If your Pages setup, branch name, or custom domain differs, your exact URLs may differ too. Open the published pages in a browser and copy the final working URLs.

## Where To Paste The URLs In Discord

In the Discord Developer Portal for your application:

1. Open your application.
2. Go to `General Information`.
3. Find the `Terms of Service URL` field.
4. Find the `Privacy Policy URL` field.
5. Paste the final published GitHub Pages URLs for the two documents.

## Before You Publish

Replace these placeholders first:

- Discord: `wolfy213`
- E-mail: `wolfydabest.dev@gmail.com`

You should also review the documents again if you add hosted APIs, analytics, external databases, cloud storage, or new data-collection features later.
