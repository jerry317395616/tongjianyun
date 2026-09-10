(() => {
    const recipePageVersion = "20260910-price-entry-1";
    const versionKey = "tongjianyun_recipe_page_version";
    const reloadKey = `${versionKey}_reloaded`;
    const cachedPages = ["tongjianyun-recipe-workbench", "tongjianyun-workbench", "weekly-recipe-nutrition-sheet"];

    try {
        if (window.localStorage.getItem(versionKey) === recipePageVersion) return;
        const hadStalePage = cachedPages.some((page) => Boolean(window.localStorage.getItem(`_page:${page}`)));
        cachedPages.forEach((page) => window.localStorage.removeItem(`_page:${page}`));
        window.localStorage.setItem(versionKey, recipePageVersion);
        if (
            hadStalePage &&
            cachedPages.some((page) => window.location.pathname.includes(page)) &&
            window.sessionStorage.getItem(reloadKey) !== recipePageVersion
        ) {
            window.sessionStorage.setItem(reloadKey, recipePageVersion);
            window.location.reload();
        }
    } catch (error) {
        console.warn("Unable to refresh the Tongjianyun recipe page cache.", error);
    }
})();
