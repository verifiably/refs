export { RefsError } from "./errors.js";
export { checkPattern, compilePattern } from "./dialect.js";
export { Curie, Scheme, type SchemeFields, parseCurie } from "./ids.js";
export {
  type Collision,
  LocalScheme,
  type LocalSchemeFields,
  Registry,
  type RegistryDocument,
} from "./registry.js";
export { type Vocabulary, parseVocabularies, releases } from "./vocab.js";
export { type About, type AboutEntry, FACET, aboutFacet, buildAbout } from "./facet.js";
