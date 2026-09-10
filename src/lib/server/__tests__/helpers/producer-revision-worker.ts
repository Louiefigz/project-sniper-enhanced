import fs from "node:fs";
import {
  commitProducerRevisionSync,
  type ProducerRevisionCommitInput,
} from "../../producer-revision-store";

const inputPath = process.argv[2];
if (!inputPath) throw new Error("producer revision worker requires an input path");
const input = JSON.parse(
  fs.readFileSync(inputPath, "utf8"),
) as ProducerRevisionCommitInput;
process.stdout.write(`${JSON.stringify(commitProducerRevisionSync(input))}\n`);
