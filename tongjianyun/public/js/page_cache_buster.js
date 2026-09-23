(() => {
    const pageCacheVersion = "20260923-classroom-1";
    const versionKey = "tongjianyun_page_cache_version";
    const reloadKey = `${versionKey}_reloaded`;
    const cachedPages = ["tongjianyun-recipe-workbench", "tongjianyun-workbench", "weekly-recipe-nutrition-sheet", "director-dashboard"];

    try {
        if (window.localStorage.getItem(versionKey) === pageCacheVersion) return;
        const hadStalePage = cachedPages.some((page) => Boolean(window.localStorage.getItem(`_page:${page}`)));
        cachedPages.forEach((page) => window.localStorage.removeItem(`_page:${page}`));
        window.localStorage.setItem(versionKey, pageCacheVersion);
        if (
            hadStalePage &&
            cachedPages.some((page) => window.location.pathname.includes(page)) &&
            window.sessionStorage.getItem(reloadKey) !== pageCacheVersion
        ) {
            window.sessionStorage.setItem(reloadKey, pageCacheVersion);
            window.location.reload();
        }
    } catch (error) {
        console.warn("Unable to refresh the Tongjianyun page cache.", error);
    }
})();
