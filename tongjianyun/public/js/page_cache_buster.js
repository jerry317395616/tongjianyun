(() => {
    const recipePageVersion = "20260813-2";
    const versionKey = "tongjianyun_recipe_page_version";
    const reloadKey = `${versionKey}_reloaded`;

    try {
        if (window.localStorage.getItem(versionKey) === recipePageVersion) return;
        const hadStalePage = Boolean(window.localStorage.getItem("_page:tongjianyun-recipe-workbench"));
        window.localStorage.removeItem("_page:tongjianyun-recipe-workbench");
        window.localStorage.setItem(versionKey, recipePageVersion);
        if (
            hadStalePage &&
            window.location.pathname.includes("tongjianyun-recipe-workbench") &&
            window.sessionStorage.getItem(reloadKey) !== recipePageVersion
        ) {
            window.sessionStorage.setItem(reloadKey, recipePageVersion);
            window.location.reload();
        }
    } catch (error) {
        console.warn("Unable to refresh the Tongjianyun recipe page cache.", error);
    }
})();
