(() => {
    const recipePageVersion = "20260813-1";
    const versionKey = "tongjianyun_recipe_page_version";

    try {
        if (window.localStorage.getItem(versionKey) === recipePageVersion) return;
        const hadStalePage = Boolean(window.localStorage.getItem("_page:tongjianyun-recipe-workbench"));
        window.localStorage.removeItem("_page:tongjianyun-recipe-workbench");
        window.localStorage.setItem(versionKey, recipePageVersion);
        if (hadStalePage && window.location.pathname.includes("tongjianyun-recipe-workbench")) {
            window.addEventListener(
                "load",
                () => {
                    window.setTimeout(() => {
                        if (!document.querySelector(".tjy-row-more")) window.location.reload();
                    }, 250);
                },
                { once: true },
            );
        }
    } catch (error) {
        console.warn("Unable to refresh the Tongjianyun recipe page cache.", error);
    }
})();
