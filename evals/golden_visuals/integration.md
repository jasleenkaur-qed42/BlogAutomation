---
title: Firebase and React Native Authentication
slug: firebase-react-native-authentication
---
# Firebase and React Native Authentication

This guide connects a React Native app to Firebase Authentication with email and password sign-in.

## Enable sign-in in the Firebase console
Open your project, go to Authentication, and enable the Email/Password provider. Without this the app receives an operation-not-allowed error.

## How the pieces connect
The app sends credentials to Firebase. Firebase returns a user and a token, and the app keeps the session.

## Which stack you are using
React Native provides the interface and Firebase provides the identity service.

## Sign in from the app
Call the sign-in method with an email and a password and handle the error.

```ts
await signInWithEmailAndPassword(auth, email, password);
```

## Conclusion
Enable the provider, wire the call, and handle errors.
