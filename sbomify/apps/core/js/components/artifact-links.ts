export interface ArtifactRoutes {
    sbom: string;
    cbom: string;
    vex: string;
    document: string;
    component: string;
}

/** Route patterns come from Django, so tables and pickers cannot invent destinations. */
export function artifactLink(
    routes: ArtifactRoutes, kind: string, componentId?: string, artifactId?: string,
): string {
    if (!componentId || !artifactId) return '#';
    const route = kind === 'document' ? routes.document :
        kind === 'cbom' ? routes.cbom : kind === 'vex' ? routes.vex : routes.sbom;
    return route.replace('__COMPONENT__', encodeURIComponent(componentId))
        .replace('__ARTIFACT__', encodeURIComponent(artifactId));
}
