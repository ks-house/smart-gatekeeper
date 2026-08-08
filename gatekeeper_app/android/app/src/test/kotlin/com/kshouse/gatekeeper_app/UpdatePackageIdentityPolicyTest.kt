package com.kshouse.gatekeeper_app

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class UpdatePackageIdentityPolicyTest {
    @Test
    fun exactPackageAndSingleSignerPass() {
        val signer = byteArrayOf(1, 2, 3)
        assertArrayEquals(
            signer,
            UpdatePackageIdentityPolicy.requireSingleSigner(
                actualPackageName = "com.kshouse.gatekeeper_app",
                expectedPackageName = "com.kshouse.gatekeeper_app",
                signerCertificates = listOf(signer),
            ),
        )
    }

    @Test
    fun wrongPackageIsRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            UpdatePackageIdentityPolicy.requireSingleSigner(
                actualPackageName = "com.attacker.repacked",
                expectedPackageName = "com.kshouse.gatekeeper_app",
                signerCertificates = listOf(byteArrayOf(1)),
            )
        }
    }

    @Test
    fun zeroOrMultipleSignersAreRejected() {
        for (signers in listOf(
            emptyList<ByteArray>(),
            listOf(byteArrayOf(1), byteArrayOf(2)),
        )) {
            assertThrows(IllegalArgumentException::class.java) {
                UpdatePackageIdentityPolicy.requireSingleSigner(
                    actualPackageName = "com.kshouse.gatekeeper_app",
                    expectedPackageName = "com.kshouse.gatekeeper_app",
                    signerCertificates = signers,
                )
            }
        }
    }
}
