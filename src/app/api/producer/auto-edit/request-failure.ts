export class RequestFailure extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}
