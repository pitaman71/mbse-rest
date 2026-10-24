/** The client side of mbse-rest: translates a mutation query into well-formed REST calls, and reads the frame stream
 * back for the UI (VISUALIZATION.md, FEA-006, CAP-013). */

import { Builders } from "@mbse/schemas/Framework";

/** A store of the app's schemas, read from the service (VISUALIZATION.md, CAP-003). */
export function newStore(): unknown {
  return new Builders.Store();
}
