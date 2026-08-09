package com.kshouse.gatekeeper_app

/** Pure fail-closed package/signer policy kept independently unit-testable. */
internal object UpdatePackageIdentityPolicy {
    fun requireSingleSigner(
        actualPackageName: String,
        expectedPackageName: String,
        signerCertificates: List<ByteArray>,
    ): ByteArray {
        require(actualPackageName == expectedPackageName) {
            "APK package identity does not match"
        }
        require(signerCertificates.size == 1) {
            "APK must have exactly one current signer"
        }
        return signerCertificates.single().also {
            require(it.isNotEmpty()) { "APK certificate is missing" }
        }
    }
}
